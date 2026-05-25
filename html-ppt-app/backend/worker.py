"""
RQ Worker entry point for html-ppt-app.

Start with:
    python worker.py                    # auto-named (hostname-pid)
    python worker.py --name worker-1    # named worker

On Windows, uses SimpleWorker (in-process execution) because neither
os.fork() nor os.wait4() are available.

On Linux/macOS, uses the default Worker with fork-based execution.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redis as redis_lib
from rq import Worker, Queue, SimpleWorker
from settings import settings


def main():
    parser = argparse.ArgumentParser(description="RQ Worker for html-ppt-app")
    parser.add_argument("--name", default=None, help="Worker name (visible in queue admin)")
    args = parser.parse_args()

    worker_name = args.name or None

    # Expose worker name to the RQ task via environment variable
    if worker_name:
        os.environ["WORKER_NAME"] = worker_name

    redis_conn = redis_lib.from_url(settings.redis_url)
    queues = [Queue("generation", connection=redis_conn)]

    worker_class = SimpleWorker if os.name == "nt" else Worker
    worker = worker_class(queues, connection=redis_conn, name=worker_name)
    worker.work()


if __name__ == "__main__":
    main()
