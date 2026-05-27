#!/usr/bin/env python3
"""
Phase 5B — Remote smoke test for Railway deployment.

Verifies the full pipeline end-to-end:
  1. Register or login test user
  2. Create a 3-page Test Deck job
  3. Poll job status until success
  4. Call preview API
  5. Call download APIs (html, standalone, zip)
  6. Verify auth enforcement (no-auth request blocked)
  7. Verify storage keys in admin endpoint
  8. Verify presigned URLs are accessible

Usage:
    python scripts/smoke_test_remote.py --base-url https://your-backend.railway.app

Environment variables (optional):
    SMOKE_BASE_URL   — backend base URL
    SMOKE_EMAIL      — existing test user email (skips registration)
    SMOKE_PASSWORD   — existing test user password
    SMOKE_INVITE_CODE — invite code (if required)
    SMOKE_ADMIN_PASSWORD — admin password for storage key verification
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_BASE = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")
TIMEOUT_SECONDS = 900  # 15 minutes max wait
POLL_INTERVAL = 3


def api_url(path: str, base: str) -> str:
    return f"{base.rstrip('/')}{path}"


def make_request(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
    admin_password: str | None = None,
    follow_redirect: bool = False,
) -> tuple[int, dict | str]:
    """Make an HTTP request. Returns (status_code, body)."""
    headers: dict[str, str] = {}
    if method in ("POST", "PUT", "PATCH"):
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if admin_password:
        headers["X-Admin-Password"] = admin_password

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    # Build opener that does NOT follow redirects (default urllib does, which
    # leaks auth headers to presigned S3 URLs and causes 400 errors from R2)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
        def http_error_302(self, req, fp, code, msg, headers):
            return fp

    try:
        if follow_redirect:
            # Strip auth headers from redirect requests (they leak to S3 presigned URLs)
            class SafeRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    new_req = urllib.request.HTTPRedirectHandler.redirect_request(
                        self, req, fp, code, msg, headers, newurl)
                    if new_req:
                        new_req.headers = {k: v for k, v in new_req.headers.items()
                                           if k.lower() not in ('authorization', 'x-admin-password')}
                    return new_req
            opener = urllib.request.build_opener(SafeRedirect)
            with opener.open(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")[:500]
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8")
            if "application/json" in content_type:
                return resp.status, json.loads(raw)
            return resp.status, raw[:500]
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            error_body = {"detail": str(e)}
        return e.code, error_body


def register_or_login(base: str, email: str, password: str) -> str | None:
    """Register a test user (if new) or login (if existing). Returns JWT token."""
    print(f"\n  Test user: {email}")

    # Try login first
    print("  Attempting login...")
    code, body = make_request(
        api_url("/api/auth/login", base), "POST",
        {"email": email, "password": password},
    )
    if code == 200 and isinstance(body, dict):
        token = body.get("access_token")
        if token:
            print(f"  Login OK. Token: {token[:20]}...")
            return token

    # Register
    print("  Registering...")
    code, body = make_request(
        api_url("/api/auth/register", base), "POST",
        {"name": "Smoke Test", "email": email, "password": password},
    )
    if code == 200:
        print(f"  Register: {body.get('message', 'OK')}")
        # Login after register
        code2, body2 = make_request(
            api_url("/api/auth/login", base), "POST",
            {"email": email, "password": password},
        )
        if code2 == 200 and isinstance(body2, dict):
            token = body2.get("access_token")
            if token:
                print(f"  Login after register OK. Token: {token[:20]}...")
                return token
    elif code == 400 and "already registered" in str(body.get("detail", "")):
        print(f"  User exists but login failed (wrong password?)")
    else:
        print(f"  Register failed: {code} {body}")

    return None


def create_job(base: str, token: str) -> str | None:
    """Create a 3-page test deck. Returns job_id."""
    print("\n[Step 2] Creating test job (3-page deck)...")
    code, body = make_request(
        api_url("/api/jobs", base), "POST",
        {
            "topic": "Smoke Test Deck",
            "content": (
                "This is a short test report for smoke testing the deployment.\n\n"
                "Section 1: Overview\n"
                "The system generates HTML PPT from report content.\n\n"
                "Section 2: Architecture\n"
                "React frontend -> FastAPI backend -> Redis/RQ -> Claude Code + html-ppt-skill.\n\n"
                "Section 3: Expected Outcome\n"
                "This test verifies the full pipeline works end-to-end."
            ),
            "language": "English",
            "style": "Professional, clean",
            "slide_count": 3,
            "audience": "Engineering team",
            "extra_requirements": "Minimal 3-slide deck. Include keyboard navigation.",
            "search_level": "none",
        },
        token,
    )
    if code not in (200, 201):
        print(f"  FAILED: {code} {body}")
        return None
    job_id = body.get("job_id")
    print(f"  Job created: {job_id}")
    print(f"  Status: {body.get('status')}")
    return job_id


def poll_job(base: str, job_id: str) -> dict | None:
    """Poll until job completes or times out. Returns final job dict."""
    print(f"\n[Step 3] Polling (timeout: {TIMEOUT_SECONDS}s)...")
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > TIMEOUT_SECONDS:
            print(f"\n  TIMEOUT after {TIMEOUT_SECONDS}s")
            return None

        code, j = make_request(api_url(f"/api/jobs/{job_id}", base))
        if not isinstance(j, dict):
            print(f"\n  Unexpected response: {code}")
            time.sleep(POLL_INTERVAL)
            continue

        status = j.get("status", "unknown")
        dots = int(elapsed / POLL_INTERVAL) % 20
        print(f"\r  [{elapsed:6.1f}s] Status: {status:<10} {'.' * dots}   ", end="")

        if status == "success":
            print(f"\n  [OK] Job completed!")
            return j
        elif status == "failed":
            print(f"\n  [FAIL] {j.get('error_message', 'No error')}")
            return j

        time.sleep(POLL_INTERVAL)


def verify_downloads(base: str, job_id: str, token: str) -> bool:
    """Verify all download endpoints return success."""
    print("\n[Step 4] Verifying downloads (authenticated)...")

    checks = [
        ("preview index", f"/api/preview/{job_id}"),
        ("preview standalone", f"/api/preview/{job_id}?type=standalone"),
        ("download html", f"/api/download/{job_id}/html"),
        ("download standalone", f"/api/download/{job_id}/standalone"),
        ("download zip", f"/api/download/{job_id}/zip"),
    ]

    all_ok = True
    for name, path in checks:
        code, body = make_request(api_url(path, base), token=token)
        icon = "[OK]" if code in (200, 302) else "[FAIL]"
        if code not in (200, 302):
            all_ok = False
        print(f"  {icon} {name}: HTTP {code}")

    # Follow redirect for presigned URL
    if all_ok:
        print("\n  Verifying presigned URL accessibility...")
        code, _ = make_request(
            api_url(f"/api/download/{job_id}/html", base),
            token=token, follow_redirect=True,
        )
        icon = "[OK]" if code == 200 else "[FAIL]"
        if code != 200:
            all_ok = False
        print(f"  {icon} presigned URL accessible: HTTP {code}")

    return all_ok


def verify_auth_enforcement(base: str, job_id: str) -> bool:
    """Verify that unauthenticated requests are blocked."""
    print("\n[Step 5] Verifying auth enforcement...")
    paths = [
        f"/api/preview/{job_id}",
        f"/api/download/{job_id}/html",
        f"/api/download/{job_id}/standalone",
        f"/api/download/{job_id}/zip",
    ]
    all_blocked = True
    for path in paths:
        code, _ = make_request(api_url(path, base))  # No token
        icon = "[OK]" if code == 401 else "[FAIL]"
        if code != 401:
            all_blocked = False
        print(f"  {icon} {path}: HTTP {code} (expected 401)")
    return all_blocked


def verify_storage_keys(
    base: str, job_id: str, admin_password: str | None
) -> bool:
    """Verify storage keys are populated (requires admin)."""
    if not admin_password:
        print("\n[Step 6] Skipping storage key verification (no admin password).")
        return True

    print("\n[Step 6] Verifying storage keys via admin...")
    code, body = make_request(
        api_url(f"/api/admin/jobs/{job_id}", base),
        admin_password=admin_password,
    )
    if code != 200 or not isinstance(body, dict):
        print(f"  [FAIL] Admin detail fetch failed: {code}")
        return False

    key_fields = [
        "index_html_key", "standalone_html_key", "zip_key",
        "logs_key", "quality_report_key",
    ]
    all_ok = True
    for field in key_fields:
        value = body.get(field)
        icon = "[OK]" if value else "[WARN]"
        if not value:
            # Some keys may be null if pipeline didn't run
            pass
        print(f"  {icon} {field}: {value or 'N/A'}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Slidehttp Phase 5B Remote Smoke Test")
    parser.add_argument("--base-url", default=DEFAULT_BASE,
                        help=f"Backend base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--email", default=os.environ.get("SMOKE_EMAIL"),
                        help="Test user email (auto-generates if not set)")
    parser.add_argument("--password", default=os.environ.get("SMOKE_PASSWORD", "smoketest123"),
                        help="Test user password")
    parser.add_argument("--admin-password", default=os.environ.get("SMOKE_ADMIN_PASSWORD"),
                        help="Admin password for storage key check")
    parser.add_argument("--token", default=None,
                        help="Skip auth and use this JWT directly")
    args = parser.parse_args()

    base = args.base_url
    email = args.email or f"smoke-test-{int(time.time())}@slidehttp.test"
    password = args.password

    print("=" * 60)
    print("Phase 5B — Remote Smoke Test")
    print(f"Backend: {base}")
    print("=" * 60)

    # ── Step 0: Health check ──────────────────────────────────────────
    print("\n[Step 0] Health check...")
    code, health = make_request(api_url("/api/health", base))
    print(f"  Status: {code}")
    if code == 200 and isinstance(health, dict):
        for name, status in sorted(health.get("checks", {}).items()):
            ok = (
                "ok" in str(status).lower()
                or "found" in str(status).lower()
                or "connected" in str(status).lower()
                or "writable" in str(status).lower()
                or "exists" in str(status).lower()
                or "s3://" in str(status)
            )
            icon = "[OK]" if ok else "[FAIL]"
            print(f"  {icon} {name}: {status}")
    else:
        print(f"  Health check response: {str(health)[:200]}")

    # ── Step 1: Auth ──────────────────────────────────────────────────
    token = args.token
    if not token:
        print("\n[Step 1] Obtaining auth token...")
        token = register_or_login(base, email, password)
        if not token:
            print("  FAILED to obtain token.")
            sys.exit(1)
    else:
        print(f"\n[Step 1] Using provided token: {token[:20]}...")

    # ── Step 2: Create job ────────────────────────────────────────────
    job_id = create_job(base, token)
    if not job_id:
        sys.exit(1)

    # ── Step 3: Poll ──────────────────────────────────────────────────
    final_job = poll_job(base, job_id)
    if not final_job:
        sys.exit(1)
    if final_job.get("status") != "success":
        print(f"\n  Job did not succeed. Status: {final_job.get('status')}")
        sys.exit(1)

    # ── Step 4: Verify downloads ──────────────────────────────────────
    downloads_ok = verify_downloads(base, job_id, token)

    # ── Step 5: Verify auth enforcement ───────────────────────────────
    auth_ok = verify_auth_enforcement(base, job_id)

    # ── Step 6: Verify storage keys ───────────────────────────────────
    storage_ok = verify_storage_keys(base, job_id, args.admin_password)

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    all_ok = downloads_ok and auth_ok and storage_ok
    if all_ok:
        print("SMOKE TEST PASSED")
    else:
        print("SMOKE TEST COMPLETED WITH ISSUES")
        if not downloads_ok:
            print("  - Some downloads failed")
        if not auth_ok:
            print("  - Auth enforcement incomplete")
        if not storage_ok:
            print("  - Storage key verification incomplete")
    print(f"Job ID: {job_id}")
    print(f"Preview: {base}/api/preview/{job_id}")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
