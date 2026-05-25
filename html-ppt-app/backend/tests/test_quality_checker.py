"""
Test suite for Phase 4E Quality Checker.

Run:  cd backend && python tests/test_quality_checker.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure the backend directory is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.pipeline.quality_checker import check

PASS = 0
FAIL = 0


def assert_eq(actual, expected, msg=""):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {msg}")
        print(f"       expected={expected!r}")
        print(f"       actual={actual!r}")


def assert_true(cond, msg=""):
    assert_eq(cond, True, msg)


def assert_gte(actual, expected_min, msg=""):
    global PASS, FAIL
    if actual >= expected_min:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ FAIL: {msg}")
        print(f"       expected >= {expected_min!r}")
        print(f"       actual={actual!r}")


# ── Helpers ──────────────────────────────────────────────────────────

def make_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="qc_test_"))


def write_html(job_dir: Path, html: str):
    (job_dir / "index.html").write_text(html, encoding="utf-8")


def write_standalone(job_dir: Path, html: str):
    (job_dir / "standalone.html").write_text(html, encoding="utf-8")


def write_zip_for(job_dir: Path):
    # Simulate: zip file in parent directory
    (job_dir.parent / f"{job_dir.name}.zip").write_text("fake zip", encoding="utf-8")


def write_logs(job_dir: Path):
    (job_dir / "logs.txt").write_text("test log", encoding="utf-8")


def make_input_cleaned(companies=None, techs=None, regions=None, metrics=None) -> dict:
    return {
        "raw_text": "Market analysis 2024. TSMC leads foundry with 69.9% share. "
                     "Global semiconductor market reached $700B in 2025, growing 12.3% CAGR. "
                     "Key regions: United States (44%), Korea (16%), China (15%). "
                     "AI chip market from $20B to $50B by 2027. Advanced packaging market $45B.",
        "clean_text": "Market analysis 2024...",
        "global_entities": {
            "companies": companies or ["TSMC", "Samsung", "Intel", "NVIDIA", "AMD"],
            "technologies": techs or ["AI", "5G", "Chiplet", "HBM4", "Quantum"],
            "regions": regions or ["United States", "Korea", "China", "Japan", "Taiwan"],
            "metrics": metrics or ["$700B", "69.9%", "12.3% CAGR", "20B", "50B", "45B"],
        },
    }


def make_deck_plan(slide_count=10) -> dict:
    slides = []
    for i in range(1, slide_count + 1):
        slides.append({
            "slide_no": i,
            "slide_title": f"Slide {i}",
            "slide_goal": f"Present data for slide {i}.",
            "source_sections": [f"S{i}"],
            "key_points": [f"Key point {i}"],
            "preferred_layout": "two-column",
        })
    return {"target_slide_count": slide_count, "deck_type": "report", "slides": slides}


def make_packed_context(slides=10) -> dict:
    packed_slides = []
    for i in range(1, slides + 1):
        packed_slides.append({
            "slide_no": i,
            "slide_title": f"Slide {i}",
            "slide_goal": f"Goal {i}",
            "key_points": [f"Key point {i}", f"Detail {i}"],
            "source_context": [{
                "section_id": f"S{i}",
                "title": f"Section {i}",
                "excerpt": f"Content for section {i}. Contains data about TSMC, 5nm, AI chips. Revenue: $50B.",
            }],
        })
    return {"slides": packed_slides}


# ── HTML templates ────────────────────────────────────────────────────

def make_good_html(slide_count=10) -> str:
    """A well-formed HTML that should pass all checks."""
    slides = ""
    for i in range(1, slide_count + 1):
        slides += f"""
    <section class="slide" data-title="Slide {i}">
        <div class="notes">Speaker notes for slide {i}. Discuss TSMC, Samsung, Intel, NVIDIA, AMD, AI, 5G, Chiplet, HBM4, Quantum trends in United States, Korea, China, Japan, Taiwan.</div>
        <h2>Slide {i} — Market Analysis</h2>
        <p>Global semiconductor market reached $700B in 2025. TSMC leads with 69.9% share.
        Key regions: United States, Korea, China, Japan, Taiwan. AI chip market growing at 12.3% CAGR.
        Samsung and Intel ramping foundry. NVIDIA and AMD driving GPU demand.
        HBM4, Chiplet, Quantum computing among top technology trends. 5G infrastructure expanding.</p>
        <p>Advanced packaging market estimated at $45B. Revenue: $50B from AI segment.</p>
    </section>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Test Deck</title>
<style>
  .deck {{ max-width: 100%; }}
  .notes {{ display: none; }}
</style>
</head>
<body>
<div class="deck" data-themes="tokyo-night,light,dark">
{slides}
</div>
<script>
document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight') nextSlide();
    if (e.key === 'ArrowLeft') prevSlide();
}});
function applyTheme(name) {{ document.body.dataset.theme = name; }}
</script>
</body>
</html>"""


def make_placeholder_html() -> str:
    """HTML with deliberate placeholder issues."""
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Test</title></head>
<body>
<div class="deck">
    <section class="slide" data-title="Intro">
        <h2>Introduction</h2>
        <p>This is a good slide with proper content.</p>
    </section>
    <section class="slide" data-title="Bad Slide 1">
        <h2>[Title]</h2>
        <p>{{company_name}} is a leader in the market. Lorem ipsum dolor sit amet.</p>
    </section>
    <section class="slide" data-title="Bad Slide 2">
        <h2>TODO: Add content</h2>
        <p>Placeholder text. Fill this section with actual content. XXX</p>
    </section>
    <section class="slide" data-title="Almost Empty">
        <h2>TBD</h2>
        <p></p>
    </section>
    <section class="slide">
        <h2>Untitled Slide</h2>
        <p>Content here. Title here.</p>
    </section>
</div>
<script>document.addEventListener('keydown', function(e) { if (e.key === 'ArrowRight') {} });</script>
</body>
</html>"""


def make_standalone_with_asset_refs() -> str:
    """standalone.html that still references local assets/ paths (bad)."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="../../assets/themes/tokyo-night.css">
<link rel="stylesheet" href="../assets/fonts/fonts.css">
</head>
<body>
<div class="deck">
    <section class="slide" data-title="Test">
        <h2>Test Slide</h2>
        <p>This slide has content. TSMC, AI, $700B. United States, Korea.</p>
    </section>
</div>
<script src="../../assets/runtime.js"></script>
<script src="../../assets/nav.js"></script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# Test 1: Normal report — passes all checks
# ═══════════════════════════════════════════════════════════════════════

def test_normal_report_passes():
    print("\n── Test 1: Normal report passes all checks ──")

    job_dir = make_dir()
    try:
        write_html(job_dir, make_good_html(10))
        write_standalone(job_dir, make_good_html(10))
        write_logs(job_dir)
        write_zip_for(job_dir)

        cleaned = make_input_cleaned()
        deck_plan = make_deck_plan(10)
        packed = make_packed_context(10)

        report = check(job_dir, deck_plan=deck_plan, packed_context=packed, input_cleaned=cleaned)

        print(f"  Status: {report['status']}, Score: {report['score']}/100")
        print(f"  Passed: {report['passed']}, Warnings: {report['warning_count']}, Failed: {report['failed']}")

        assert_eq(report["status"], "pass", "Overall status should be 'pass'")
        assert_gte(report["score"], 80, "Score should be >= 80")
        assert_gte(report["passed"], 10, "Should have at least 10 passing checks")
        assert_true(report["failed"] == 0, "Should have zero failures")

        # Verify key check results
        check_names = {c["name"]: c["result"] for c in report["checks"]}
        assert_eq(check_names.get("index_html_exists"), "PASS", "index.html exists")
        assert_eq(check_names.get("standalone_integrity"), "PASS", "Standalone is clean")
        assert_eq(check_names.get("placeholders_clean"), "PASS", "No placeholders")
        assert_eq(check_names.get("speaker_notes"), "PASS", "Speaker notes present")
        assert_eq(check_names.get("theme_switching"), "PASS", "Theme switching present")
        assert_eq(check_names.get("keyboard_navigation"), "PASS", "Keyboard navigation present")
        assert_eq(check_names.get("entity_retention"), "PASS", "Entity retention good")
        assert_eq(check_names.get("data_retention"), "PASS", "Data retention good")

    finally:
        shutil.rmtree(job_dir.parent, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Test 2: Placeholder HTML — caught by quality checker
# ═══════════════════════════════════════════════════════════════════════

def test_placeholders_detected():
    print("\n── Test 2: Placeholder HTML detected ──")

    job_dir = make_dir()
    try:
        write_html(job_dir, make_placeholder_html())

        report = check(job_dir)  # no pipeline artifacts

        print(f"  Status: {report['status']}, Score: {report['score']}/100")
        print(f"  Passed: {report['passed']}, Warnings: {report['warning_count']}, Failed: {report['failed']}")

        # Check that placeholders were found
        check_names = {c["name"]: c["result"] for c in report["checks"]}

        # At least one placeholder check should fire
        placeholder_warns = [c for c in report["checks"]
                           if c["name"].startswith("placeholder_") and c["result"] == "WARN"]
        assert_true(len(placeholder_warns) >= 3,
                   f"Should find >=3 placeholder issues, found {len(placeholder_warns)}")

        # Specific placeholders
        for expected in ["placeholder_bracket_title", "placeholder_mustache",
                        "placeholder_lorem_ipsum", "placeholder_todo",
                        "placeholder_xxx_marker", "placeholder_tbd",
                        "placeholder_untitled", "placeholder_title_here",
                        "placeholder_fill_this", "placeholder_content_here"]:
            result = check_names.get(expected)
            if result == "WARN":
                print(f"  ✓ Found: {expected}")

        # empty_slides should warn about nearly-empty slide
        empty_check = [c for c in report["checks"] if c["name"] == "empty_slides"][0]
        assert_true(empty_check["result"] in ("WARN", "FAIL"), "Empty slides should be flagged")

        # Theme switching / keyboard may be missing
        assert_true(check_names.get("speaker_notes") in ("WARN", "FAIL"), "No speaker notes")

    finally:
        shutil.rmtree(job_dir.parent, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Test 3: standalone.html still references assets/ — FAIL
# ═══════════════════════════════════════════════════════════════════════

def test_standalone_asset_refs_detected():
    print("\n── Test 3: standalone.html with asset refs detected ──")

    job_dir = make_dir()
    try:
        # Good index.html, but bad standalone.html
        write_html(job_dir, make_good_html(10))
        write_standalone(job_dir, make_standalone_with_asset_refs())
        write_logs(job_dir)
        write_zip_for(job_dir)

        report = check(job_dir)

        print(f"  Status: {report['status']}, Score: {report['score']}/100")

        check_names = {c["name"]: c["result"] for c in report["checks"]}

        # standalone integrity MUST fail
        assert_eq(check_names.get("standalone_integrity"), "FAIL",
                 "standalone.html with local assets/ refs must FAIL")

        # index.html exists — should pass
        assert_eq(check_names.get("index_html_exists"), "PASS", "index.html exists")

        # Check that errors list includes standalone
        error_names = [e["name"] for e in report["errors"]]
        assert_true("standalone_integrity" in error_names,
                   f"standalone_integrity should be in errors list, got {error_names}")

    finally:
        shutil.rmtree(job_dir.parent, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 4E — Quality Checker Tests")
    print("=" * 60)

    test_normal_report_passes()
    test_placeholders_detected()
    test_standalone_asset_refs_detected()

    total = PASS + FAIL
    print(f"\n{'=' * 60}")
    print(f"Results: {PASS}/{total} passed")
    if FAIL > 0:
        print(f"        {FAIL} FAILURE(S)!")
        sys.exit(1)
    else:
        print("All tests passed!")
        sys.exit(0)
