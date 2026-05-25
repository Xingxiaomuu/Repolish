"""
Step 3: Context Packing — for each slide in the deck plan, package the
relevant original text excerpts (not summaries) for Claude Code to use.
"""

import re
from typing import Any


# Max context characters per slide — keep it tight but data-rich
MAX_CONTEXT_PER_SLIDE = 2400


def pack(cleaned: dict[str, Any], deck_plan: dict[str, Any]) -> dict[str, Any]:
    """
    Build packed_context from cleaned input and deck plan.

    For each slide, extracts original text from source_sections,
    trims intelligently (keeping entity-rich sentences), and returns
    per-slide context blocks.
    """
    sections = cleaned.get("sections", [])
    section_map = {s["section_id"]: s for s in sections}

    packed_slides = []
    for slide in deck_plan.get("slides", []):
        source_ids = slide.get("source_sections", [])
        source_context = _build_source_context(source_ids, section_map)
        packed_slides.append({
            "slide_no": slide.get("slide_no", 0),
            "slide_title": slide.get("slide_title", ""),
            "slide_goal": slide.get("slide_goal", ""),
            "preferred_layout": slide.get("preferred_layout", "two-column"),
            "key_points": slide.get("key_points", []),
            "speaker_notes_direction": slide.get("speaker_notes_direction", ""),
            "source_context": source_context,
        })

    return {"slides": packed_slides}


def _build_source_context(source_ids: list[str],
                          section_map: dict) -> list[dict[str, Any]]:
    """Extract and trim original text from referenced sections."""
    entries = []
    for sid in source_ids:
        sec = section_map.get(sid)
        if not sec:
            continue

        full_text = sec.get("text", "")
        if not full_text.strip():
            continue

        excerpt = _trim_text(full_text, MAX_CONTEXT_PER_SLIDE // max(1, len(source_ids)))
        entries.append({
            "section_id": sid,
            "title": sec.get("title", ""),
            "excerpt": excerpt,
        })
    return entries


def _trim_text(text: str, max_chars: int) -> str:
    """Trim text to roughly max_chars while preserving entity-rich sentences."""
    if len(text) <= max_chars:
        return text

    sentences = _split_sentences(text)

    # Score each sentence: entity-rich sentences get priority
    scored = []
    for sent in sentences:
        score = _entity_score(sent)
        scored.append((score, sent))

    # Sort by score descending, keep high-score sentences up to max_chars
    scored.sort(key=lambda x: x[0], reverse=True)

    kept_sentences = []
    total = 0
    for score, sent in scored:
        if total + len(sent) > max_chars:
            break
        kept_sentences.append(sent)
        total += len(sent) + 1  # +1 for space between sentences

    # Re-sort by original order
    original_order = {s: i for i, s in enumerate(sentences)}
    kept_sentences.sort(key=lambda s: original_order.get(s, 9999))

    result = " ".join(kept_sentences)

    # If we cut too much, add truncation marker
    if len(result) < len(text) * 0.6:
        result += f"\n\n[... Full text: {len(text)} chars, excerpt: {len(result)} chars. Key data preserved.]"

    return result


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, handling both English and Chinese punctuation."""
    # Split on sentence boundaries
    raw = re.split(r"(?<=[.!?。！？])\s+", text)
    return [s.strip() for s in raw if len(s.strip()) > 5]


def _entity_score(sentence: str) -> int:
    """Score a sentence based on entity density (higher = more important)."""
    score = 0
    # Numbers with units
    score += len(re.findall(r"\d+(?:\.\d+)?\s*%?", sentence)) * 2
    # Currency or metric keywords
    score += len(re.findall(r"\$|USD|EUR|RMB|CNY|million|billion|trillion|CAGR|YoY|QoQ|万亿|亿", sentence, re.IGNORECASE)) * 3
    # Capitalized proper nouns (likely companies/people)
    score += len(re.findall(r"\b[A-Z][a-z]+\s+(?:Inc|Ltd|Corp|Group|Holdings|LLC|Technologies|Systems|Solutions|Networks|Labs)\b", sentence)) * 5
    # Technology keywords
    tech_count = len(re.findall(r"\b(?:AI|ML|LLM|Cloud|SaaS|Blockchain|IoT|5G|Quantum|GenAI|Digital Twin|Edge|API|SDK)\b", sentence, re.IGNORECASE))
    score += tech_count * 3
    # Year references
    score += len(re.findall(r"\b20\d{2}\b", sentence)) * 2
    # Bullet points or list markers
    score += len(re.findall(r"^[•\-\*\d+\.]\s", sentence)) * 1
    # Question sentences (often important framing)
    if sentence.rstrip().endswith("?"):
        score += 2
    return score
