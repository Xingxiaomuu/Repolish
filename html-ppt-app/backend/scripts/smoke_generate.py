"""
Phase 5A — Smoke test for Railway deployment.

Creates a minimal job, submits it to the API, and polls until completion.
Verifies the full pipeline: API → Redis/RQ → Worker → Claude Code → index.html.

Usage:
    # Local (backend running on localhost:8000):
    python scripts/smoke_generate.py

    # Against a deployed Railway backend:
    python scripts/smoke_generate.py --base-url https://your-app.railway.app

    # With token (if testing against authenticated endpoint):
    python scripts/smoke_generate.py --token <JWT_TOKEN>
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Add parent dir to path so we can import backend modules if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_BASE = os.environ.get("PUBLIC_BACKEND_URL", "http://localhost:8000")
TIMEOUT_SECONDS = 600  # 10 minutes max wait
POLL_INTERVAL = 3  # seconds


def api_url(path: str, base: str) -> str:
    return f"{base.rstrip('/')}{path}"


def make_request(url: str, method: str = "GET", body: dict | None = None,
                 token: str | None = None) -> tuple[int, dict]:
    """Make an HTTP request and return (status_code, json_body)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = {}
        try:
            error_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        return e.code, error_body


def register_and_login(base: str) -> str | None:
    """Register a test user and return a JWT token."""
    test_email = f"smoke-test-{int(time.time())}@slidehttp.test"
    test_name = "Smoke Test"
    test_password = "smoketest123"

    print(f"\n  Registering test user: {test_email} ...")
    code, body = make_request(
        api_url("/api/auth/register", base), "POST",
        {"name": test_name, "email": test_email, "password": test_password},
    )
    if code not in (200, 400):
        print(f"  Register failed: {code} {body}")
        return None

    # If already registered (400), that's OK — try login anyway
    print(f"  Register: {body.get('message', 'OK')}")

    print(f"  Logging in...")
    code, body = make_request(
        api_url("/api/auth/login", base), "POST",
        {"email": test_email, "password": test_password},
    )
    if code != 200:
        print(f"  Login failed: {code} {body}")
        return None

    token = body.get("access_token")
    if token:
        print(f"  Token obtained: {token[:20]}...")
    return token


def run(base: str, token: str | None = None):
    """Run the smoke test."""
    print("=" * 60)
    print("Phase 5A — Smoke Test: Railway Deployment")
    print("=" * 60)

    # ── Step 0: Health check ──────────────────────────────────────────
    print("\n[Step 0] Health check...")
    code, health = make_request(api_url("/api/health", base))
    print(f"  Status: {code}")
    if code == 200:
        checks = health.get("checks", {})
        for name, status in sorted(checks.items()):
            icon = "✓" if ("ok" in str(status).lower() or "found" in str(status).lower() or "connected" in str(status).lower() or "writable" in str(status).lower() or "exists" in str(status).lower()) else "✗"
            print(f"  {icon} {name}: {status}")
    else:
        print(f"  Health check failed: {health}")
        # Continue anyway — maybe the endpoint doesn't exist yet

    # ── Step 1: Auth (if no token provided) ──────────────────────────
    if not token:
        print("\n[Step 1] Obtaining auth token...")
        token = register_and_login(base)
        if not token:
            print("  FAILED to obtain token. Try --token <JWT_TOKEN>")
            sys.exit(1)
    else:
        print(f"\n[Step 1] Using provided token: {token[:20]}...")

    # ── Step 2: Create job ────────────────────────────────────────────
    print("\n[Step 2] Creating test job...")
    job_body = {
        "topic": "Test Deck — Smoke Test",
        "content": "This is a short test report for smoke testing the deployment.\n\n"
                   "Section 1: Overview\n"
                   "The system generates HTML PPT from report content.\n\n"
                   "Section 2: Architecture\n"
                   "React frontend → FastAPI backend → Redis/RQ → Claude Code + html-ppt-skill.\n\n"
                   "Section 3: Expected Outcome\n"
                   "This test verifies the full pipeline works end-to-end.",
        "language": "English",
        "style": "Professional, clean",
        "slide_count": 3,
        "audience": "Engineering team",
        "extra_requirements": "Minimal 3-slide deck. Include keyboard navigation.",
        "search_level": "none",
    }

    code, resp = make_request(
        api_url("/api/jobs", base), "POST", job_body, token,
    )
    if code not in (200, 201):
        print(f"  FAILED to create job: {code} {resp}")
        sys.exit(1)

    job_id = resp.get("job_id")
    print(f"  Job created: {job_id}")
    print(f"  Status: {resp.get('status')}")
    print(f"  Remaining generations: {resp.get('remaining_generations', 'N/A')}")

    # ── Step 3: Poll until complete ───────────────────────────────────
    print(f"\n[Step 3] Polling job status (timeout: {TIMEOUT_SECONDS}s)...")
    start = time.time()
    dots = 0
    while True:
        elapsed = time.time() - start
        if elapsed > TIMEOUT_SECONDS:
            print(f"\n  TIMEOUT after {TIMEOUT_SECONDS}s")
            sys.exit(1)

        code, j = make_request(api_url(f"/api/jobs/{job_id}", base))
        status = j.get("status", "unknown")

        # Progress indicator
        dots = (dots + 1) % 20
        print(f"\r  [{elapsed:6.1f}s] Status: {status:<10} {'.' * dots}   ", end="")

        if status == "success":
            print(f"\n  ✓ Job completed successfully!")
            break
        elif status == "failed":
            print(f"\n  ✗ Job FAILED: {j.get('error_message', 'No error message')}")
            sys.exit(1)

        time.sleep(POLL_INTERVAL)

    # ── Step 4: Verify outputs ────────────────────────────────────────
    print("\n[Step 4] Verifying outputs...")

    # Check download URLs
    urls_to_check = [
        ("index.html (download)", f"/api/download/{job_id}/html"),
        ("standalone.html (download)", f"/api/download/{job_id}/standalone"),
        ("ZIP download", f"/api/download/{job_id}/zip"),
    ]

    all_ok = True
    for label, url_path in urls_to_check:
        code, _ = make_request(api_url(url_path, base))
        icon = "✓" if code == 200 else "✗"
        if code != 200:
            all_ok = False
        print(f"  {icon} {label}: HTTP {code}")

    # Check quality report via artifacts
    code, artifacts = make_request(
        api_url(f"/api/jobs/{job_id}/artifacts", base),
    )
    if code == 200:
        arts = artifacts.get("artifacts", [])
        qr = [a for a in arts if a["filename"] == "quality_report.json"]
        if qr:
            print(f"  ✓ quality_report.json: {qr[0]['size']} bytes")
        else:
            print(f"  ⚠ quality_report.json not found")
    else:
        print(f"  ⚠ artifacts endpoint: HTTP {code}")

    # ── Step 5: Summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    if all_ok:
        print("SMOKE TEST PASSED — All outputs generated successfully.")
        print(f"Job ID: {job_id}")
        print(f"Preview: {base}/outputs/{job_id}/index.html")
    else:
        print("SMOKE TEST COMPLETED WITH WARNINGS — Some outputs missing.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slidehttp smoke test")
    parser.add_argument("--base-url", default=DEFAULT_BASE,
                        help=f"Backend base URL (default: {DEFAULT_BASE})")
    parser.add_argument("--token", default=None,
                        help="JWT token (auto-registers if not provided)")
    args = parser.parse_args()

    run(args.base_url, args.token)
