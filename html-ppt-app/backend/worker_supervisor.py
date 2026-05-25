"""
Worker Supervisor — launches and monitors multiple RQ worker subprocesses.

Usage:
    python worker_supervisor.py               # default 2 workers
    WORKER_COUNT=3 python worker_supervisor.py  # 3 workers
    python worker_supervisor.py --count 3       # 3 workers (arg takes priority)

Cross-platform: Windows, Linux, macOS.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import redis as redis_lib
from settings import settings

BACKEND_DIR = Path(__file__).resolve().parent


def _startup_cleanup():
    """Full startup cleanup: workers, failed RQ jobs, stuck DB jobs.

    1. Delete ALL rq:worker:* keys + rq:workers set (handles UUID-named workers).
    2. Re-enqueue any abandoned RQ jobs whose DB status is still queued/running.
    3. Reset DB jobs stuck in 'running' back to 'queued'.
    4. Delete orphaned rq:job:* keys and clear the failed registry.
    """
    r = None
    try:
        r = redis_lib.from_url(settings.redis_url)
    except Exception as e:
        print(f"  Warning: Cannot connect to Redis: {e}\n")
        return

    # ── 1. Clear all worker registrations ──────────────────────────────
    try:
        keys = r.keys("rq:worker:*")
        if keys:
            r.delete(*keys)
            print(f"  Cleaned up {len(keys)} stale worker key(s) from Redis.")
        else:
            print("  No stale worker keys found in Redis.")

        stale = r.smembers("rq:workers")
        if stale:
            r.delete("rq:workers")
            print(f"  Removed {len(stale)} stale worker name(s) from rq:workers set.")
    except Exception as e:
        print(f"  Warning: Could not clean Redis worker registry: {e}\n")
        r = None  # Don't trust the connection for further operations

    # ── 2. Re-enqueue abandoned RQ jobs ────────────────────────────────
    if r:
        try:
            from rq.registry import FailedJobRegistry
            from rq import Queue

            q = Queue("generation", connection=r)
            failed_registry = FailedJobRegistry("generation", connection=r)
            abandoned_job_ids = list(failed_registry.get_job_ids())
            requeued_count = 0

            if abandoned_job_ids:
                # Lazy import DB (only needed if there are failed jobs)
                from database import init_db, SessionLocal
                from models import Job
                from datetime import datetime, timezone

                init_db()
                db = SessionLocal()
                try:
                    for rq_job_id in abandoned_job_ids:
                        rq_job = q.fetch_job(rq_job_id)
                        if not rq_job or not rq_job.args:
                            continue

                        our_job_id = rq_job.args[0]
                        db_job = db.query(Job).filter(Job.id == our_job_id).first()
                        if not db_job:
                            # Orphaned RQ job — DB entry doesn't exist
                            continue

                        if db_job.status in ("queued", "running"):
                            # Re-enqueue with same args and our job_id
                            from tasks.generate_deck import generate_deck
                            q.enqueue(generate_deck, our_job_id,
                                      job_timeout=settings.claude_timeout)
                            db_job.status = "queued"
                            db_job.worker_name = None
                            db_job.started_at = None
                            now = datetime.now(timezone.utc)
                            note = f"[{now.isoformat()}] Re-queued after worker restart."
                            if db_job.error_message:
                                db_job.error_message = note + "\n" + db_job.error_message
                            else:
                                db_job.error_message = note
                            requeued_count += 1

                    db.commit()
                finally:
                    db.close()

                # Remove all failed jobs from the registry
                for rq_job_id in abandoned_job_ids:
                    failed_registry.remove(rq_job_id, delete_job=True)

                if requeued_count > 0:
                    print(f"  Re-enqueued {requeued_count} abandoned job(s) from failed registry.")
                total_failed = len(abandoned_job_ids)
                if total_failed > 0:
                    print(f"  Cleaned up {total_failed} failed RQ job(s) from registry.")
            else:
                print("  No abandoned jobs in RQ failed registry.")
        except Exception as e:
            print(f"  Warning: Could not re-enqueue abandoned jobs: {e}")

    # ── 3. Reset DB jobs stuck in 'running' ────────────────────────────
    try:
        from database import init_db, SessionLocal
        from models import Job
        from datetime import datetime, timezone

        init_db()
        db = SessionLocal()
        try:
            stuck = db.query(Job).filter(Job.status == "running").all()
            if stuck:
                now = datetime.now(timezone.utc)
                for j in stuck:
                    j.status = "queued"
                    j.worker_name = None
                    j.started_at = None
                    note = f"[{now.isoformat()}] Worker restart — job returned to queue."
                    if j.error_message:
                        j.error_message = note + "\n" + j.error_message
                    else:
                        j.error_message = note
                db.commit()
                print(f"  Reset {len(stuck)} stuck 'running' job(s) back to 'queued'.")
            else:
                print("  No stuck running jobs in DB.")
        finally:
            db.close()
    except Exception as e:
        print(f"  Warning: Could not reset stuck running jobs: {e}")

    # ── 4. Clean orphaned rq:job:* keys ────────────────────────────────
    if r:
        try:
            orphaned = r.keys("rq:job:*")
            if orphaned:
                r.delete(*orphaned)
                print(f"  Cleaned up {len(orphaned)} orphaned rq:job key(s).")
        except Exception as e:
            print(f"  Warning: Could not clean rq:job keys: {e}")

    print()


def get_worker_count() -> int:
    """Resolve worker count: CLI arg > WORKER_COUNT env > default 2."""
    parser = argparse.ArgumentParser(description="Launch multiple RQ workers")
    parser.add_argument("--count", type=int, default=None, help="Number of workers (default: env WORKER_COUNT or 2)")
    args, _ = parser.parse_known_args()

    if args.count is not None:
        return max(1, args.count)
    try:
        return max(1, int(os.environ.get("WORKER_COUNT", "2")))
    except (ValueError, TypeError):
        return 2


def main():
    count = get_worker_count()
    print(f"=== Worker Supervisor ===\n")

    # Verify Redis is reachable before doing anything
    try:
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis at {settings.redis_url}")
        print(f"  {e}")
        print(f"\nMake sure Redis is running before starting the worker supervisor:")
        print(f"  - Windows (MSYS2/WSL): redis-server")
        print(f"  - Windows (native):    redis-server.exe (or install via winget/memurai)")
        print(f"  - Docker:              docker run -d -p 6379:6379 redis:7-alpine")
        sys.exit(1)

    # Clean up stale worker registrations from previous runs
    _startup_cleanup()

    print(f"Starting {count} worker(s)...\n")

    processes: dict[str, subprocess.Popen] = {}

    try:
        for i in range(1, count + 1):
            name = f"worker-{i}"
            p = subprocess.Popen(
                [sys.executable, str(BACKEND_DIR / "worker.py"), "--name", name],
                cwd=str(BACKEND_DIR),
                # No pipe — let worker stdout/stderr go directly to this terminal
                stdout=None,
                stderr=None,
            )
            processes[name] = p
            print(f"  [{name}] PID {p.pid} — started")

        print(f"\nAll {count} worker(s) running. Press Ctrl+C to stop.\n")

        # Monitor loop — poll every 2 seconds
        while True:
            for name, p in list(processes.items()):
                ret = p.poll()
                if ret is not None:
                    print(f"\n  [{name}] PID {p.pid} — exited with code {ret}")
                    del processes[name]

            if not processes:
                print("\nAll workers have exited. Supervisor shutting down.")
                break

            time.sleep(2)

    except KeyboardInterrupt:
        print(f"\n\nShutting down {len(processes)} worker(s)...")
        for name, p in processes.items():
            print(f"  [{name}] PID {p.pid} — terminating...")
            p.terminate()
        # Give them a moment to exit gracefully
        time.sleep(2)
        # Force-kill any stragglers
        for name, p in list(processes.items()):
            if p.poll() is None:
                print(f"  [{name}] PID {p.pid} — force killing...")
                p.kill()
        print("All workers stopped.")
        _startup_cleanup()


if __name__ == "__main__":
    main()
