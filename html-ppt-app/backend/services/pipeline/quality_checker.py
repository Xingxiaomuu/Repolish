"""
Step 6: Quality Checker — validate generated HTML against inputs.
Checks files, HTML structure, placeholders, empty slides, entity/data retention,
slide-source correspondence, and standalone integrity.
"""

import json
import re
from pathlib import Path
from typing import Any


def check(
    job_dir: Path,
    deck_plan: dict[str, Any] | None = None,
    packed_context: dict[str, Any] | None = None,
    input_cleaned: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run quality checks on the generated output files.

    If pipeline artifacts (deck_plan, packed_context, input_cleaned) are
    provided, entity/data/source-correspondence checks are enabled.
    Without them, only file/HTML/placeholder/empty-slide/standalone checks run.
    """
    report: dict[str, Any] = {
        "checks": [],
        "warnings": [],
        "errors": [],
        "passed": 0,
        "warning_count": 0,
        "failed": 0,
        "score": 0,
        "status": "unknown",
    }

    # ── A. File checks ─────────────────────────────────────────────────
    _check_files(report, job_dir)

    # If index.html doesn't exist, we can't do the rest
    index_path = job_dir / "index.html"
    if not index_path.is_file():
        _finalize(report)
        return report

    html = index_path.read_text(encoding="utf-8", errors="replace")
    file_size = index_path.stat().st_size

    # Check file size
    if file_size < 100:
        _add(report, "file_size_minimum", "FAIL", f"index.html is only {file_size} bytes — likely empty or broken.")
    else:
        _add(report, "file_size_minimum", "PASS", f"index.html is {file_size:,} bytes.")

    # ── B. HTML structure checks ───────────────────────────────────────
    _check_html_structure(report, html, deck_plan)

    # ── C. Placeholder checks ──────────────────────────────────────────
    _check_placeholders(report, html)

    # ── D. Empty slide checks ──────────────────────────────────────────
    _check_empty_slides(report, html)

    # ── E. Key entity retention (requires input_cleaned) ───────────────
    if input_cleaned:
        _check_entity_retention(report, html, input_cleaned)

    # ── F. Data retention (requires input_cleaned) ─────────────────────
    if input_cleaned:
        _check_data_retention(report, html, input_cleaned)

    # ── G. Slide-source correspondence (requires packed_context) ───────
    if packed_context and deck_plan:
        _check_source_correspondence(report, html, packed_context)

    # ── H. Standalone integrity ────────────────────────────────────────
    _check_standalone(report, job_dir)

    _finalize(report)
    return report


# ═══════════════════════════════════════════════════════════════════════════
# A. File checks
# ═══════════════════════════════════════════════════════════════════════════

def _check_files(report: dict, job_dir: Path):
    files_to_check = [
        ("index_html_exists", "index.html", "index.html"),
        ("standalone_html_exists", "standalone.html", "standalone.html"),
        ("zip_exists", f"{job_dir.name}.zip", "zip bundle"),
        ("logs_exist", "logs.txt", "logs.txt"),
    ]
    for name, filename, label in files_to_check:
        path = job_dir.parent / filename if name == "zip_exists" else job_dir / filename
        if path.is_file():
            _add(report, name, "PASS", f"{label} found ({path.stat().st_size:,} bytes).")
        else:
            if name in ("index_html_exists",):
                _add(report, name, "FAIL", f"{label} not found.")
            else:
                _add(report, name, "WARN", f"{label} not found.")


# ═══════════════════════════════════════════════════════════════════════════
# B. HTML structure checks
# ═══════════════════════════════════════════════════════════════════════════

def _check_html_structure(report: dict, html: str, deck_plan: dict | None):
    # B1: slide count
    slides = re.findall(r'<section[^>]*class="[^"]*slide[^"]*"', html, re.IGNORECASE)
    if not slides:
        slides = re.findall(r'<section\b[^>]*', html, re.IGNORECASE)
    slide_count = len(slides)

    if slide_count == 0:
        _add(report, "slide_elements", "FAIL", "No <section class=\"slide\"> elements found.")
    else:
        target = deck_plan.get("target_slide_count") if deck_plan else None
        if target and target > 0:
            ratio = slide_count / target
            if 0.7 <= ratio <= 1.5:
                _add(report, "slide_count", "PASS", f"Slide count: {slide_count} (target: {target}).")
            elif 0.4 <= ratio <= 2.5:
                _add(report, "slide_count", "WARN", f"Slide count {slide_count} differs from target {target} (ratio: {ratio:.1f}).")
            else:
                _add(report, "slide_count", "WARN", f"Slide count {slide_count} far from target {target} (ratio: {ratio:.1f}).")
        else:
            _add(report, "slide_count", "PASS", f"Slide count: {slide_count}.")
        _add(report, "slide_elements", "PASS", f"{slide_count} <section class=\"slide\"> elements found.")

    # B2: data-title on each slide
    slides_with_title = len(re.findall(r'<section[^>]*data-title\s*=\s*"[^"]*"', html, re.IGNORECASE))
    if slide_count > 0 and slides_with_title >= slide_count * 0.8:
        _add(report, "data_title_attributes", "PASS", f"{slides_with_title}/{slide_count} slides have data-title.")
    elif slide_count > 0 and slides_with_title >= slide_count * 0.4:
        _add(report, "data_title_attributes", "WARN", f"Only {slides_with_title}/{slide_count} slides have data-title.")
    elif slide_count > 0:
        _add(report, "data_title_attributes", "WARN", f"Only {slides_with_title}/{slide_count} slides have data-title — navigation may be poor.")
    else:
        _add(report, "data_title_attributes", "PASS", "No slides to check for data-title.")

    # B3: speaker notes (.notes or <aside>)
    has_notes = bool(
        re.search(r'class="[^"]*notes[^"]*"', html, re.IGNORECASE)
        or re.search(r'<aside\b', html, re.IGNORECASE)
        or re.search(r'data-notes\s*=', html, re.IGNORECASE)
        or re.search(r'speaker.notes', html, re.IGNORECASE)
        or re.search(r'\.notes\s*\{', html, re.IGNORECASE)
    )
    if has_notes:
        notes_count = len(re.findall(r'class="[^"]*notes[^"]*"', html, re.IGNORECASE))
        _add(report, "speaker_notes", "PASS", f"Speaker notes detected ({notes_count} occurrences).")
    else:
        _add(report, "speaker_notes", "WARN", "No speaker notes found — may not have been generated.")

    # B4: deck container
    has_deck = bool(re.search(r'class="[^"]*deck[^"]*"', html, re.IGNORECASE))
    if has_deck:
        _add(report, "deck_container", "PASS", "Deck container (.deck) found.")
    else:
        _add(report, "deck_container", "WARN", "No .deck container found — layout may be broken.")

    # B5: runtime.js or inline runtime
    has_runtime = bool(
        re.search(r'runtime\.js', html, re.IGNORECASE)
        or re.search(r'<script[^>]*>[\s\S]{50,}</script>', html)
    )
    if has_runtime:
        _add(report, "runtime_present", "PASS", "Runtime (js or inline) detected.")
    else:
        _add(report, "runtime_present", "WARN", "No runtime.js or inline script block found — interactivity may be missing.")

    # B6: theme switching (data-themes or theme switching JS)
    has_theme = bool(
        re.search(r'data-themes?\b', html, re.IGNORECASE)
        or re.search(r'(?:applyTheme|setTheme|theme-select|theme-switch|cycleTheme)', html, re.IGNORECASE)
        or re.search(r'class="[^"]*theme[^"]*"', html, re.IGNORECASE)
    )
    if has_theme:
        _add(report, "theme_switching", "PASS", "Theme switching mechanism detected.")
    else:
        _add(report, "theme_switching", "WARN", "No theme switching found — static theme only.")

    # B7: keyboard navigation
    has_kb = bool(
        re.search(r'addEventListener\s*\(\s*["\']key', html, re.IGNORECASE)
        or re.search(r'onkeydown', html, re.IGNORECASE)
        or re.search(r'(?:ArrowLeft|ArrowRight|ArrowUp|ArrowDown)', html)
        or re.search(r'\.key\s*===', html)
        or re.search(r'keyCode', html, re.IGNORECASE)
    )
    if has_kb:
        _add(report, "keyboard_navigation", "PASS", "Keyboard navigation detected.")
    else:
        _add(report, "keyboard_navigation", "WARN", "No keyboard navigation detected.")


# ═══════════════════════════════════════════════════════════════════════════
# C. Placeholder checks
# ═══════════════════════════════════════════════════════════════════════════

_PLACEHOLDER_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (name, label, pattern)
    ("mustache", "{{...}} template markers", re.compile(r"\{\{[^}]*\}\}")),
    ("bracket_title", "[Title] brackets", re.compile(r"\[Title\]", re.IGNORECASE)),
    ("title_here", "'Title here' text", re.compile(r"Title\s+here", re.IGNORECASE)),
    ("lorem_ipsum", "Lorem ipsum", re.compile(r"Lorem\s+ipsum", re.IGNORECASE)),
    ("todo", "TODO markers", re.compile(r"TODO\b", re.IGNORECASE)),
    ("placeholder_word", "'Placeholder' text", re.compile(r"Placeholder", re.IGNORECASE)),
    ("untitled", "'Untitled' text", re.compile(r"Untitled", re.IGNORECASE)),
    ("fill_this", "'Fill this' pattern", re.compile(r"fill[-\s](?:this|in|here)", re.IGNORECASE)),
    ("xxx_marker", "XXX markers", re.compile(r"\bXXX\b")),
    ("tbd", "TBD markers", re.compile(r"\bTBD\b", re.IGNORECASE)),
    ("content_here", "'Content here' text", re.compile(r"Content\s+here", re.IGNORECASE)),
]


def _check_placeholders(report: dict, html: str):
    found_any = False
    for name, label, pattern in _PLACEHOLDER_PATTERNS:
        matches = pattern.findall(html)
        if matches:
            found_any = True
            unique = list(dict.fromkeys(matches))[:5]
            snippet = ", ".join(repr(m) for m in unique)
            _add(report, f"placeholder_{name}", "WARN", f"Found {label}: {snippet}")

    if not found_any:
        _add(report, "placeholders_clean", "PASS", "No placeholder text detected.")


# ═══════════════════════════════════════════════════════════════════════════
# D. Empty slide checks
# ═══════════════════════════════════════════════════════════════════════════

def _check_empty_slides(report: dict, html: str):
    # Extract each slide section
    slide_blocks = re.findall(
        r'<section[^>]*class="[^"]*slide[^"]*"[^>]*>(.*?)</section>',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not slide_blocks:
        # Try simpler pattern — any <section>
        slide_blocks = re.findall(r'<section\b[^>]*>(.*?)</section>', html, re.DOTALL)

    empty_count = 0
    title_only_count = 0
    for block in slide_blocks:
        # Strip HTML tags for text content
        text = re.sub(r'<[^>]+>', '', block).strip()
        # Strip whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 5:
            empty_count += 1
        elif len(text) < 30:
            title_only_count += 1

    total = len(slide_blocks)
    if total == 0:
        _add(report, "empty_slides", "PASS", "No slides found to check for emptiness.")
        return

    if empty_count == 0 and title_only_count == 0:
        _add(report, "empty_slides", "PASS", f"All {total} slides have content.")
    else:
        parts = []
        if empty_count > 0:
            parts.append(f"{empty_count} nearly empty (<5 chars text)")
        if title_only_count > 0:
            parts.append(f"{title_only_count} title-only (<30 chars text)")
        detail = f"{', '.join(parts)} out of {total} total."
        if empty_count > total * 0.2:
            _add(report, "empty_slides", "FAIL", detail)
        elif empty_count > 0 or title_only_count > total * 0.3:
            _add(report, "empty_slides", "WARN", detail)
        else:
            _add(report, "empty_slides", "PASS", f"Minor: {detail}")


# ═══════════════════════════════════════════════════════════════════════════
# E. Key entity retention
# ═══════════════════════════════════════════════════════════════════════════

def _check_entity_retention(report: dict, html: str, input_cleaned: dict):
    entities = input_cleaned.get("global_entities", {})
    html_lower = html.lower()

    categories: list[tuple[str, str, int]] = [
        ("companies", "company names", 2),
        ("technologies", "technology terms", 2),
        ("regions", "region names", 1),
    ]

    all_found = 0
    all_total = 0
    missing_important: list[str] = []

    for key, label, min_for_pass in categories:
        items = entities.get(key, [])
        if not items:
            continue
        # Take up to 20 most important (first ones)
        sample = items[:20]
        found = sum(1 for item in sample if item.lower() in html_lower)
        all_found += found
        all_total += len(sample)

        # Report notable misses (first 5 items are usually most important)
        top_items = sample[:5]
        top_missing = [item for item in top_items if item.lower() not in html_lower]
        if top_missing:
            missing_important.extend(top_missing[:3])

    if all_total == 0:
        _add(report, "entity_retention", "PASS", "No entities in source to check.")
        return

    coverage = all_found / all_total
    if coverage >= 0.7:
        _add(report, "entity_retention", "PASS",
             f"Entity retention: {coverage:.0%} ({all_found}/{all_total} key entities found).")
    elif coverage >= 0.4:
        detail = f"Entity retention: {coverage:.0%} ({all_found}/{all_total})."
        if missing_important:
            detail += f" Missing: {', '.join(missing_important[:5])}."
        _add(report, "entity_retention", "WARN", detail)
    else:
        detail = f"Entity retention: {coverage:.0%} ({all_found}/{all_total})."
        if missing_important:
            detail += f" Missing: {', '.join(missing_important[:5])}."
        _add(report, "entity_retention", "WARN", detail)


# ═══════════════════════════════════════════════════════════════════════════
# F. Data retention (metrics / numbers)
# ═══════════════════════════════════════════════════════════════════════════

_DATA_PATTERNS = [
    (r'\d+(?:\.\d+)?%', "percentages"),
    (r'(?:USD|RMB|CNY|EUR|JPY|GBP)\s*\d+', "currency amounts"),
    (r'\$\s*\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[MBT]|\s*million|\s*billion|\s*trillion)?', "dollar amounts"),
    (r'\d+(?:,\d{3})*(?:\.\d+)?\s*(?:million|billion|trillion)', "large numbers"),
    (r'CAGR', "CAGR references"),
    (r'\b20\d{2}\b', "year references"),
    (r'(?:market\s+size|revenue|shipment|volume)', "market metrics", re.IGNORECASE),
]


def _check_data_retention(report: dict, html: str, input_cleaned: dict):
    source_text = input_cleaned.get("raw_text", "") or input_cleaned.get("clean_text", "")
    if not source_text:
        _add(report, "data_retention", "PASS", "No source text to compare data against.")
        return

    # Count numbers in source (rough: any digit-containing token)
    source_numbers = len(re.findall(r'\d+(?:\.\d+)?', source_text))
    html_numbers = len(re.findall(r'\d+(?:\.\d+)?', html))

    if source_numbers == 0:
        _add(report, "data_retention", "PASS", "No numeric data in source.")
        return

    # Check each data pattern
    missing_patterns = []
    for pattern, label, *flags in _DATA_PATTERNS:
        flag = flags[0] if flags else 0
        source_count = len(re.findall(pattern, source_text, flag))
        html_count = len(re.findall(pattern, html, flag))
        if source_count > 0 and html_count == 0:
            missing_patterns.append(label)

    ratio = html_numbers / max(1, source_numbers)
    if ratio >= 0.3 and not missing_patterns:
        _add(report, "data_retention", "PASS",
             f"Data retention: {ratio:.0%} numeric density ({html_numbers}/{source_numbers} numbers).")
    elif ratio >= 0.1 and len(missing_patterns) <= 2:
        detail = f"Data retention: {ratio:.0%} numeric density."
        if missing_patterns:
            detail += f" Missing: {', '.join(missing_patterns[:3])}."
        _add(report, "data_retention", "WARN", detail)
    elif ratio > 0:
        detail = f"Low data retention: {ratio:.0%} numeric density."
        if missing_patterns:
            detail += f" Missing: {', '.join(missing_patterns[:5])}."
        detail += f" Possible over-summarization."
        _add(report, "data_retention", "WARN", detail)
    else:
        _add(report, "data_retention", "FAIL",
             f"No numeric data retained from source ({source_numbers} source numbers). Over-summarization likely.")


# ═══════════════════════════════════════════════════════════════════════════
# G. Slide-source correspondence
# ═══════════════════════════════════════════════════════════════════════════

def _check_source_correspondence(report: dict, html: str, packed_context: dict):
    packed_slides = packed_context.get("slides", [])
    if not packed_slides:
        _add(report, "source_correspondence", "PASS", "No packed context to check.")
        return

    # Get all slide sections from HTML
    html_slides = re.findall(r'<section\b[^>]*>(.*?)</section>', html, re.DOTALL)

    matched = 0
    total = 0
    completely_unmatched = 0

    for i, pslide in enumerate(packed_slides):
        key_points = pslide.get("key_points", [])
        if not key_points:
            continue

        total += 1
        # Find corresponding HTML slide (by position)
        if i < len(html_slides):
            slide_html = html_slides[i].lower()
        else:
            slide_html = ""  # slide doesn't exist

        # Check how many key points have word overlap
        points_found = 0
        for kp in key_points:
            # Extract significant words (4+ chars, non-stop words)
            words = [w for w in re.findall(r'\b[a-z]{4,}\b', kp.lower()) if w not in _STOP_WORDS]
            if words:
                overlap = sum(1 for w in words if w in slide_html)
                if overlap >= len(words) * 0.3 or overlap >= 2:
                    points_found += 1

        if key_points and points_found / len(key_points) >= 0.5:
            matched += 1
        elif points_found == 0 and slide_html:
            completely_unmatched += 1

    if total == 0:
        _add(report, "source_correspondence", "PASS", "No key points to check correspondence for.")
        return

    match_rate = matched / total
    if match_rate >= 0.7:
        _add(report, "source_correspondence", "PASS",
             f"Slide-source match: {match_rate:.0%} ({matched}/{total} slides match key points).")
    elif match_rate >= 0.4:
        _add(report, "source_correspondence", "WARN",
             f"Slide-source match: {match_rate:.0%} ({matched}/{total}). {completely_unmatched} slides may have lost source content.")
    else:
        _add(report, "source_correspondence", "WARN",
             f"Poor slide-source match: {match_rate:.0%} ({matched}/{total}). {completely_unmatched} slides have no source overlap.")


_STOP_WORDS = {
    "this", "that", "these", "those", "with", "from", "have", "been",
    "were", "their", "they", "will", "would", "could", "should", "about",
    "also", "each", "which", "there", "when", "where", "other", "more",
    "some", "only", "over", "into", "than", "then", "just", "what",
}


# ═══════════════════════════════════════════════════════════════════════════
# H. Standalone integrity
# ═══════════════════════════════════════════════════════════════════════════

def _check_standalone(report: dict, job_dir: Path):
    standalone_path = job_dir / "standalone.html"
    if not standalone_path.is_file():
        _add(report, "standalone_integrity", "WARN", "standalone.html not found — cannot check integrity.")
        return

    text = standalone_path.read_text(encoding="utf-8", errors="replace")

    issues = []

    # Check for references to local assets/ directory
    asset_refs = re.findall(
        r'(?:src|href)\s*=\s*["\x27](?:\.\./|[^"\x27]*assets/[^"\x27]*)["\x27]',
        text, re.IGNORECASE,
    )
    if asset_refs:
        unique_refs = list(dict.fromkeys(asset_refs))[:5]
        issues.append(f"References assets/ directory: {', '.join(unique_refs)}")

    # Check for ../../ paths
    parent_refs = re.findall(r"(?:src|href)\s*=\s*[\"']\.\./", text)
    if parent_refs:
        issues.append(f"{len(parent_refs)} relative parent-path reference(s)")

    # Check for <link> to external CDN that requires network (not truly standalone)
    external_css = re.findall(
        r'<link[^>]*href\s*=\s*["\']https?://[^"\']*["\'][^>]*>',
        text, re.IGNORECASE,
    )
    # Not a hard failure, but note it
    if external_css:
        issues.append(f"{len(external_css)} external CSS reference(s) — requires network")

    if issues:
        has_asset_refs = any("assets/" in i or "../" in i for i in issues)
        if has_asset_refs:
            _add(report, "standalone_integrity", "FAIL",
                 f"Standalone still references local paths: {'; '.join(issues)}")
        else:
            _add(report, "standalone_integrity", "WARN",
                 f"Standalone notes: {'; '.join(issues)}")
    else:
        size_kb = standalone_path.stat().st_size / 1024
        _add(report, "standalone_integrity", "PASS",
             f"Standalone is self-contained ({size_kb:.1f} KB, no local asset refs).")


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _add(report: dict, name: str, result: str, message: str):
    entry = {"name": name, "result": result, "message": message}
    report["checks"].append(entry)
    if result == "PASS":
        report["passed"] += 1
    elif result == "WARN":
        report["warning_count"] += 1
        report["warnings"].append(entry)
    else:  # FAIL
        report["failed"] += 1
        report["errors"].append(entry)


def _finalize(report: dict):
    total_checks = len(report["checks"])
    if total_checks == 0:
        report["score"] = 0
        report["status"] = "unknown"
        return

    # Each check contributes equally to the 0-100 score
    # PASS = full points, WARN = half, FAIL = 0
    points_per_check = 100 / total_checks
    score = 0.0
    for c in report["checks"]:
        if c["result"] == "PASS":
            score += points_per_check
        elif c["result"] == "WARN":
            score += points_per_check * 0.5
    report["score"] = round(score)

    # Determine overall status
    has_critical_fail = any(
        c["name"] in ("index_html_exists", "standalone_integrity")
        and c["result"] == "FAIL"
        for c in report["checks"]
    )

    if report["failed"] > 1 or has_critical_fail:
        report["status"] = "fail"
    elif report["failed"] >= 1 or report["warning_count"] >= 5:
        report["status"] = "warning"
    elif report["score"] >= 80:
        report["status"] = "pass"
    elif report["score"] >= 50:
        report["status"] = "warning"
    else:
        report["status"] = "fail"
