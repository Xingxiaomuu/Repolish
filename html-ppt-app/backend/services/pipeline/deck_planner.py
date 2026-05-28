"""
Step 2: Deck Planning — generate a per-slide plan from cleaned input.
Rule-based: maps sections to slides, guesses layout from content patterns.
No LLM call — the plan is saved as JSON for downstream use.
"""

import json
import re
from pathlib import Path
from typing import Any


def plan(cleaned: dict[str, Any], target_slide_count: int = 10,
         audience: str = "", style: str = "professional",
         language: str = "English") -> dict[str, Any]:
    """
    Generate a deck plan from cleaned input data.

    Returns a dict with the deck plan structure.
    """
    sections = cleaned.get("sections", [])
    total_chars = sum(s.get("char_count", 0) for s in sections)
    section_count = len(sections)

    if section_count == 0:
        return _minimal_plan(target_slide_count, audience, language)

    # Determine content-to-slide ratio
    # Long text (>8000 chars) → reading deck, more slides
    # Short text → presentation deck, fewer slides
    if total_chars > 15000:
        deck_type = "reading deck (dense report)"
        chars_per_slide = 1800
    elif total_chars > 8000:
        deck_type = "reading deck"
        chars_per_slide = 1400
    elif total_chars > 3000:
        deck_type = "mixed reading / presentation"
        chars_per_slide = 1000
    else:
        deck_type = "presentation deck"
        chars_per_slide = 600

    # Estimate slide count from content — used only as a floor / fallback
    content_slide_estimate = max(3, total_chars // chars_per_slide)
    # Respect user's explicit target; only fall back to content estimate when not specified
    if target_slide_count and target_slide_count > 0:
        slide_count = target_slide_count
    else:
        slide_count = content_slide_estimate

    # Clamp to reasonable range (min 3, max 40)
    slide_count = max(3, min(40, slide_count))

    # Ensure we have at least enough slides for content density
    slide_count = max(slide_count, content_slide_estimate // 2 + 1)

    # Ensure we have at least one content slide per 2 sections
    slide_count = max(slide_count, section_count // 2 + 1)

    # Build slides
    slides = _build_slides(sections, slide_count, deck_type, total_chars, cleaned.get("tables", []),
                           cleaned.get("global_entities", {}))

    return {
        "target_slide_count": len(slides),
        "deck_type": deck_type,
        "audience": audience or "general",
        "language": language,
        "content_sections_total": section_count,
        "content_chars_total": total_chars,
        "slides": slides,
    }


# ── Internal slide builders ─────────────────────────────────────────────

def _build_slides(sections: list[dict], target: int, deck_type: str,
                  total_chars: int, tables: list[dict],
                  entities: dict) -> list[dict[str, Any]]:
    """Build slide list from sections."""
    slides = []

    # Slide 1: Cover
    slides.append(_make_cover(sections))

    # Optional TOC if >4 content sections
    content_slides_needed = target - 2  # minus cover and closing
    if len(sections) > 4 and content_slides_needed >= 5:
        slides.append(_make_toc(sections))
        content_slides_needed -= 1

    # Map sections to content slides
    section_count = len(sections)
    if section_count <= content_slides_needed:
        # One section per slide (or split long sections)
        for i, sec in enumerate(sections):
            slides.append(_section_to_slide(sec, i + 1, tables, entities))
    else:
        # Group sections into slides
        groups = _group_sections(sections, content_slides_needed)
        for gi, group in enumerate(groups):
            slides.append(_group_to_slide(group, gi + 1, tables, entities))

    # Closing / Thank You / Summary slide
    slides.append(_make_closing(sections, entities))

    # Renumber all slides
    for i, s in enumerate(slides):
        s["slide_no"] = i + 1

    return slides


def _make_cover(sections: list[dict]) -> dict[str, Any]:
    title = sections[0].get("title", "Report") if sections else "Report"
    return {
        "slide_no": 0,
        "slide_title": title,
        "slide_goal": "Present the report title, date, and key highlights to set context.",
        "source_sections": [],
        "key_points": [],
        "preferred_layout": "cover",
        "speaker_notes_direction": "Introduce the report topic and scope.",
    }


def _make_toc(sections: list[dict]) -> dict[str, Any]:
    toc_items = [s.get("title", f"Section {i+1}") for i, s in enumerate(sections[:12])]
    return {
        "slide_no": 0,
        "slide_title": "Table of Contents",
        "slide_goal": "Provide an overview of the report structure.",
        "source_sections": [],
        "key_points": toc_items,
        "preferred_layout": "toc",
        "speaker_notes_direction": "Walk through the report structure.",
    }


def _make_closing(sections: list[dict], entities: dict) -> dict[str, Any]:
    key_companies = entities.get("companies", [])[:3]
    key_regions = entities.get("regions", [])[:3]
    summary_parts = []
    if key_companies:
        summary_parts.append(f"Key players: {', '.join(key_companies)}")
    if key_regions:
        summary_parts.append(f"Key regions: {', '.join(key_regions)}")

    return {
        "slide_no": 0,
        "slide_title": "Summary & Outlook",
        "slide_goal": "Summarize key findings and provide forward-looking statements.",
        "source_sections": [s.get("section_id", "") for s in sections[-2:]],
        "key_points": summary_parts if summary_parts else ["See report for details."],
        "preferred_layout": "two-column",
        "speaker_notes_direction": "Summarize main conclusions and next steps.",
    }


def _section_to_slide(sec: dict, seq: int, tables: list[dict],
                      entities: dict) -> dict[str, Any]:
    """Convert a single section into a slide."""
    title = sec.get("title", f"Section {seq}")
    text = sec.get("text", "")
    sec_entities = sec.get("detected_entities", {})

    # Extract key points: first 2-3 sentences
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    key_points = [s.strip() for s in sentences[:3] if len(s.strip()) > 10]

    # Guess layout
    layout = _guess_layout(text, sec_entities, tables)

    # Speaker notes direction
    notes_dir = f"Present key findings from '{title}'. Highlight data and entities detected in this section."

    return {
        "slide_no": 0,
        "slide_title": title,
        "slide_goal": f"Convey the main points of '{title}' — preserve original data, company names, and metrics.",
        "source_sections": [sec.get("section_id", "")],
        "key_points": key_points[:5],
        "preferred_layout": layout,
        "speaker_notes_direction": notes_dir,
    }


def _group_to_slide(group: list[dict], seq: int, tables: list[dict],
                    entities: dict) -> dict[str, Any]:
    """Convert a group of related sections into a single slide."""
    titles = [s.get("title", "") for s in group]
    merged_title = " & ".join(titles[:3])
    if len(titles) > 3:
        merged_title += f" (+{len(titles) - 3} more)"

    merged_text = "\n\n".join(s.get("text", "") for s in group)
    sec_ids = [s.get("section_id", "") for s in group]

    # Extract key points from merged text
    sentences = re.split(r"(?<=[.!?。！？])\s+", merged_text)
    key_points = [s.strip() for s in sentences[:4] if len(s.strip()) > 15]

    # Merge entities from all sections
    all_companies = []
    all_tech = []
    all_metrics = []
    for s in group:
        e = s.get("detected_entities", {})
        all_companies.extend(e.get("companies", []))
        all_tech.extend(e.get("technologies", []))
        all_metrics.extend(e.get("metrics", []))
    merged_entities = {
        "companies": list(dict.fromkeys(all_companies))[:10],
        "technologies": list(dict.fromkeys(all_tech))[:10],
        "regions": [],
        "metrics": list(dict.fromkeys(all_metrics))[:10],
    }

    layout = _guess_layout(merged_text, merged_entities, tables)
    notes = f"Cover the combined topics: {', '.join(titles[:5])}. Preserve original data."

    return {
        "slide_no": 0,
        "slide_title": merged_title,
        "slide_goal": f"Cover multiple related sections. Keep original data, company names, and metrics intact.",
        "source_sections": sec_ids,
        "key_points": key_points[:5],
        "preferred_layout": layout,
        "speaker_notes_direction": notes,
    }


def _group_sections(sections: list[dict], target_groups: int) -> list[list[dict]]:
    """Greedy: assign sections to slides, each slide gets ~equal char count."""
    total_chars = sum(s.get("char_count", 0) for s in sections)
    chars_per_group = max(400, total_chars // max(1, target_groups))

    groups = []
    current_group = []
    current_chars = 0

    for sec in sections:
        sec_chars = sec.get("char_count", 0)
        if current_group and current_chars + sec_chars > chars_per_group * 1.5:
            groups.append(current_group)
            current_group = []
            current_chars = 0
        current_group.append(sec)
        current_chars += sec_chars

    if current_group:
        groups.append(current_group)

    # Don't let groups get too fragmented — merge small tail groups
    while len(groups) > target_groups and len(groups) >= 2:
        # Merge the two smallest groups
        groups.sort(key=len)
        groups[0].extend(groups[1])
        groups.pop(1)

    return groups


def _guess_layout(text: str, entities: dict, tables: list[dict]) -> str:
    """Guess a preferred slide layout from content patterns."""
    metrics = entities.get("metrics", [])
    companies = entities.get("companies", [])

    # Check for tables in this section's text
    if tables:
        # See if any table text appears in this section
        for t in tables:
            if t.get("raw", "")[:50] in text:
                return "table"

    # Many metrics → KPI grid
    if len(metrics) >= 5:
        return "kpi-grid"

    # Multiple companies → comparison
    if len(companies) >= 3:
        return "comparison"

    # Many key numbers → data-heavy
    number_count = len(re.findall(r"\d+(?:\.\d+)?%?", text))
    if number_count > 10:
        return "two-column"  # one side text, one side data

    # Default: two-column for balanced text+visual
    char_count = len(text)
    if char_count > 1500:
        return "two-column"

    return "two-column"


def _minimal_plan(slide_count: int, audience: str, language: str) -> dict[str, Any]:
    return {
        "target_slide_count": slide_count,
        "deck_type": "presentation deck",
        "audience": audience or "general",
        "language": language,
        "content_sections_total": 0,
        "content_chars_total": 0,
        "slides": [
            {"slide_no": 1, "slide_title": "Cover", "slide_goal": "Title page",
             "source_sections": [], "key_points": [],
             "preferred_layout": "cover", "speaker_notes_direction": ""},
            {"slide_no": 2, "slide_title": "Content", "slide_goal": "Main content",
             "source_sections": [], "key_points": [],
             "preferred_layout": "two-column", "speaker_notes_direction": ""},
        ],
    }
