#!/usr/bin/env python3
"""Phase 5B — Worker health check script.

Checks that all worker dependencies are available.
Useful for Railway worker service health monitoring.

Usage:
    python scripts/worker_health_check.py
    # Exit 0 if all checks pass, 1 otherwise.

Environment:
    DATABASE_URL, REDIS_URL, STORAGE_PROVIDER, S3_*
    CLAUDE_CODE_COMMAND
"""

import json
import os
import shutil
import sys
from pathlib import Path

# Ensure the backend directory is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settings import settings  # noqa: E402


def _find_skill_dir() -> Path | None:
    """Walk up from cwd looking for .agents/skills/html-ppt/."""
    for p in [Path.cwd(), *Path.cwd().parents]:
        skill = p / ".agents" / "skills" / "html-ppt"
        if skill.is_dir():
            return skill
    return None


def check_database() -> tuple[bool, str]:
    try:
        from sqlalchemy import text
        from database import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return True, f"connected ({settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url[:50]})"
    except Exception as e:
        return False, f"error: {e}"


def check_redis() -> tuple[bool, str]:
    try:
        import redis
        conn = redis.from_url(settings.redis_url)
        if conn.ping():
            return True, "connected"
        return False, "no response"
    except Exception as e:
        return False, f"error: {e}"


def check_storage() -> tuple[bool, str]:
    try:
        from services.storage import get_storage_client
        storage = get_storage_client()
        ok, msg = storage.health_check()
        return ok, msg
    except Exception as e:
        return False, f"error: {e}"


def check_claude() -> tuple[bool, str]:
    cmd = settings.claude_code_command
    resolved = shutil.which(cmd)
    if resolved:
        return True, f"found ({resolved})"
    alt = shutil.which("claude")
    if alt:
        return True, f"found as 'claude' ({alt})"
    return False, f"NOT FOUND ({cmd})"


def check_skill() -> tuple[bool, str]:
    skill_dir = _find_skill_dir()
    if skill_dir and (skill_dir / "SKILL.md").is_file():
        return True, f"found ({skill_dir})"
    return False, "NOT FOUND — .agents/skills/html-ppt/ not found"


def main() -> int:
    checks = {
        "database": check_database(),
        "redis": check_redis(),
        "storage": check_storage(),
        "claude_command": check_claude(),
        "html_ppt_skill": check_skill(),
    }

    output = {}
    all_ok = True
    for name, (ok, msg) in checks.items():
        status = "ok" if ok else "FAIL"
        if not ok:
            all_ok = False
        output[name] = status
        output[f"{name}_detail"] = msg

    output["overall"] = "pass" if all_ok else "fail"

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
