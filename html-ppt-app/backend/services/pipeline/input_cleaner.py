"""
Step 1: Input Cleaning — parse long text into structured sections with entity detection.
Pure regex/rule-based, no LLM call.
"""

import re
import json
from typing import Any


# ── Section header detection patterns ───────────────────────────────────

_SECTION_PATTERNS = [
    # Markdown headers: ## Title or ### Title
    re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE),
    # Numbered sections: 1. Title, 1.1 Title, Section 1: Title, Part I:
    re.compile(r"^(?:(?:Section|Part|Chapter)\s*\d+[.:]\s*.+|(?:\d+\.)+\s+.+)$", re.MULTILINE),
    # All-caps short lines (likely section headers, max 120 chars)
    re.compile(r"^[A-Z一-鿿][A-Z一-鿿\s\-/,&]{4,100}$", re.MULTILINE),
    # Lines ending with colon that are short (like "Market Overview:" or "市场概况：")
    re.compile(r"^.{2,80}[:：]$", re.MULTILINE),
    # Separator-style markers
    re.compile(r"^[=\-*~]{3,}$", re.MULTILINE),
    # Bracketed / parenthesized headers: [Market Analysis], (Part 1)
    re.compile(r"^[\[(][^)\]]+[\])]\s*$", re.MULTILINE),
]


# ── Entity detection patterns ───────────────────────────────────────────

_COMPANY_SUFFIX = r"(?:Inc\.?|Incorporated|Ltd\.?|Limited|Corp\.?|Corporation|LLC|LLP|PLC|Group|Holdings|Enterprises|International|Co\.?,?\s*Ltd\.?|S\.A\.|AG|GmbH|KK|株式会社|有限公司|集团|科技)"
_COMPANY_PATTERN = re.compile(
    rf"\b(?:[A-Z一-鿿][\w一-鿿&.\-\s]{{1,40}}?\s*(?:{_COMPANY_SUFFIX}))\b"
)

_TECH_KEYWORDS = [
    "AI", "Artificial Intelligence", "ML", "Machine Learning", "Deep Learning",
    "NLP", "Natural Language Processing", "LLM", "Large Language Model",
    "Transformer", "GPT", "BERT", "Neural Network", "CNN", "RNN", "GAN",
    "Computer Vision", "Speech Recognition", "Generative AI", "Diffusion Model",
    "Blockchain", "Web3", "DeFi", "Smart Contract", "NFT",
    "Cloud Computing", "SaaS", "PaaS", "IaaS", "Edge Computing", "Fog Computing",
    "IoT", "Internet of Things", "5G", "6G", "Wi-Fi 6", "Bluetooth",
    "Quantum Computing", "Quantum", "Semiconductor", "Chip", "FPGA", "ASIC",
    "AR", "VR", "MR", "XR", "Augmented Reality", "Virtual Reality",
    "Robot", "Robotics", "Autonomous", "ADAS", "LiDAR", "Radar",
    "Biotech", "CRISPR", "mRNA", "Genomics", "Proteomics",
    "Big Data", "Data Lake", "Data Warehouse", "ETL", "Streaming",
    "Kubernetes", "Docker", "Microservices", "Serverless", "DevOps",
    "Cybersecurity", "Zero Trust", "Encryption", "Firewall", "SOC",
    "Digital Twin", "Metaverse", "Spatial Computing",
    "EV", "Electric Vehicle", "Battery", "Solid State", "Fast Charging",
    "Solar", "Wind", "Hydrogen", "Renewable", "Carbon Capture",
]
_TECH_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in sorted(_TECH_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Regions: curated list of countries + major cities/regions
_REGIONS_LIST = [
    "United States", "US", "USA", "America", "North America", "Latin America",
    "Canada", "Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru",
    "Europe", "EU", "European Union", "Western Europe", "Eastern Europe", "CEE",
    "United Kingdom", "UK", "Germany", "France", "Italy", "Spain", "Netherlands",
    "Sweden", "Switzerland", "Norway", "Denmark", "Finland", "Poland", "Austria",
    "Belgium", "Portugal", "Ireland", "Russia", "Turkey", "Greece", "Czech",
    "Asia", "Asia-Pacific", "APAC", "Southeast Asia", "SEA", "South Asia", "East Asia",
    "China", "Chinese", "Japan", "Japanese", "Korea", "South Korea", "Korean",
    "India", "Indian", "Indonesia", "Thailand", "Vietnam", "Malaysia", "Singapore",
    "Philippines", "Taiwan", "Hong Kong", "Australia", "New Zealand", "ANZ",
    "Middle East", "MENA", "GCC", "UAE", "Saudi Arabia", "Israel", "Qatar",
    "Africa", "Sub-Saharan Africa", "South Africa", "Nigeria", "Kenya", "Egypt",
    "Greater China", "Greater Bay Area", "GBA", "Yangtze River Delta",
    "Silicon Valley", "Shenzhen", "Beijing", "Shanghai", "Tokyo", "London", "New York",
]
_REGION_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(r) for r in sorted(_REGIONS_LIST, key=len, reverse=True)) + r")\b",
)

# Metrics: numbers with units
_METRIC_PATTERN = re.compile(
    r"(?:(?:USD|RMB|CNY|EUR|JPY|GBP)\s*)?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|bps|percent|million|billion|trillion|M|B|T|万亿|亿|万)"
    r"|(?:\d+(?:,\d{3})*(?:\.\d+)?\s*(?:CAGR|YoY|QoQ|USD|RMB|CNY|EUR|JPY|\$|€|¥|£))"
    r"|\$\s*\d+(?:,\d{3})*(?:\.\d+)?\s*(?:[MBT]|million|billion)?"
    r"|\d+(?:,\d{3})*(?:\.\d+)?%"
    r"|\d+\s*(?:million|billion|trillion)",
    re.IGNORECASE,
)

# Detect table-like blocks (lines with pipe | or tab separators, or CSV-like)
_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
_TABLE_SEP_PATTERN = re.compile(r"^\s*\|[\s\-:|]+\|\s*$", re.MULTILINE)


# ── Main cleaning function ──────────────────────────────────────────────

def clean(raw_text: str) -> dict[str, Any]:
    """Clean input text and return structured JSON with sections and entities."""
    if not raw_text or not raw_text.strip():
        return _empty_result(raw_text or "")

    # Normalize line endings and whitespace
    clean_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ blank lines to 2
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    # Strip trailing/leading whitespace but preserve internal structure
    clean_text = clean_text.strip()

    # Detect sections
    sections = _detect_sections(clean_text)

    # Detect tables
    tables = _detect_tables(clean_text)

    # Detect global entities
    global_entities = _detect_entities(clean_text)

    # Detect entities per section
    for sec in sections:
        sec["detected_entities"] = _detect_entities(sec["text"])

    return {
        "raw_text": raw_text,
        "clean_text": clean_text,
        "sections": sections,
        "tables": tables,
        "global_entities": global_entities,
    }


# ── Internal helpers ────────────────────────────────────────────────────

def _empty_result(raw_text: str) -> dict[str, Any]:
    return {
        "raw_text": raw_text,
        "clean_text": "",
        "sections": [],
        "tables": [],
        "global_entities": {"companies": [], "technologies": [], "regions": [], "metrics": []},
    }


def _detect_sections(text: str) -> list[dict[str, Any]]:
    """Split text into sections by detecting headers and other structural cues."""
    # Find all potential section break points
    break_positions: list[int] = []

    for pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            pos = m.start()
            # Don't add if it's at position 0 (first section)
            if pos > 0:
                break_positions.append(pos)

    # Remove duplicates and sort
    break_positions = sorted(set(break_positions))

    # If no sections detected, split by length (~2000 chars per section)
    if not break_positions:
        return _split_by_length(text, 2000)

    # Build sections from break positions
    sections = []
    prev_pos = 0
    for i, pos in enumerate(break_positions):
        # Find the actual header line
        segment = text[prev_pos:pos].strip()
        if not segment:
            prev_pos = pos
            continue

        # Extract title from the first line
        lines = segment.split("\n")
        title = lines[0].strip().lstrip("#").strip()
        if len(title) > 120:
            title = title[:117] + "..."

        sections.append({
            "section_id": f"S{i + 1}",
            "title": title,
            "text": segment,
            "char_count": len(segment),
            "detected_entities": {},
        })
        prev_pos = pos

    # Last section
    segment = text[prev_pos:].strip()
    if segment:
        lines = segment.split("\n")
        title = lines[0].strip().lstrip("#").strip()
        if len(title) > 120:
            title = title[:117] + "..."
        sections.append({
            "section_id": f"S{len(sections) + 1}",
            "title": title,
            "text": segment,
            "char_count": len(segment),
            "detected_entities": {},
        })

    # Renumber
    for i, sec in enumerate(sections):
        sec["section_id"] = f"S{i + 1}"

    return sections


def _split_by_length(text: str, max_chars: int) -> list[dict[str, Any]]:
    """Split text into sections by character length, trying to break at paragraph boundaries."""
    paragraphs = text.split("\n\n")
    sections = []
    current_text = ""
    current_title = ""
    section_num = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if not current_text:
            current_title = para.split("\n")[0].strip()[:120]
            current_text = para
        elif len(current_text) + len(para) + 2 <= max_chars:
            current_text += "\n\n" + para
        else:
            section_num += 1
            sections.append({
                "section_id": f"S{section_num}",
                "title": current_title,
                "text": current_text,
                "char_count": len(current_text),
                "detected_entities": {},
            })
            current_title = para.split("\n")[0].strip()[:120]
            current_text = para

    if current_text.strip():
        section_num += 1
        sections.append({
            "section_id": f"S{section_num}",
            "title": current_title,
            "text": current_text,
            "char_count": len(current_text),
            "detected_entities": {},
        })

    return sections


def _detect_tables(text: str) -> list[dict[str, Any]]:
    """Detect markdown-style table blocks in text."""
    tables = []
    # Find consecutive pipe-delimited rows
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if _TABLE_ROW_PATTERN.match(lines[i]):
            table_start = i
            rows = []
            while i < len(lines) and _TABLE_ROW_PATTERN.match(lines[i]):
                row = lines[i]
                # Skip separator rows like |---|---|
                if not _TABLE_SEP_PATTERN.match(row):
                    cells = [c.strip() for c in row.strip().strip("|").split("|")]
                    rows.append(cells)
                i += 1
            if rows:
                tables.append({
                    "table_id": f"T{len(tables) + 1}",
                    "start_line": table_start + 1,
                    "header": rows[0] if len(rows) > 0 else [],
                    "rows": rows[1:] if len(rows) > 1 else [],
                    "raw": "\n".join(lines[table_start:i]),
                })
        else:
            i += 1
    return tables


def _detect_entities(text: str) -> dict[str, list[str]]:
    """Detect companies, technologies, regions, and metrics in text."""
    companies = list(dict.fromkeys(m.group(0).strip() for m in _COMPANY_PATTERN.finditer(text)))
    technologies = list(dict.fromkeys(m.group(0) for m in _TECH_PATTERN.finditer(text)))
    regions = list(dict.fromkeys(m.group(0) for m in _REGION_PATTERN.finditer(text)))
    metrics = list(dict.fromkeys(m.group(0).strip() for m in _METRIC_PATTERN.finditer(text)))

    return {
        "companies": companies[:50],       # cap to avoid bloat
        "technologies": technologies[:50],
        "regions": regions[:30],
        "metrics": metrics[:50],
    }
