"""
Step 4: Prompt Builder — generates the final prompt for Claude Code + html-ppt-skill.
Includes deck plan and per-slide packed context so the model preserves original data.
"""

import json
from pathlib import Path
from typing import Any


def build(topic: str, language: str, style: str, audience: str,
          extra_requirements: str, deck_plan: dict[str, Any],
          packed_context: dict[str, Any], job_dir: Path,
          search_level: str = "none") -> str:
    """
    Build the full generation prompt string.

    The prompt instructs Claude Code to:
    1. Invoke the html-ppt skill
    2. Follow the deck plan structure
    3. Use per-slide source_context (original text, not summaries)
    4. Preserve data, entities, and structure from the source
    """
    slide_count = deck_plan.get("target_slide_count", 10)
    deck_type = deck_plan.get("deck_type", "presentation deck")

    # Build the deck plan summary table for the prompt
    plan_summary = _format_deck_plan_summary(deck_plan)

    # Build the per-slide context blocks
    context_blocks = _format_context_blocks(packed_context)

    extra = extra_requirements.strip() if extra_requirements else ""

    # Build search instructions
    search_block = _build_search_block(search_level, language, slide_count)

    prompt = f"""ACT NOW — use the Skill tool immediately to invoke html-ppt. Then use Write to create the index.html file.

【Task】Generate an HTML presentation following a detailed slide-by-slide plan. Each slide has specific source context — use it, do NOT summarize it away.

【Output Directory】You MUST write index.html and all assets to: {job_dir}

【Topic】{topic}

【Language】{language}

【Style Requirements】{style}

【Audience】{audience}

【Extra Requirements】{extra if extra else "(none)"}
{search_block}
【Deck Type】{deck_type}
- Target slide count: {slide_count}
- Do NOT fabricate data. If a slide's source_context lacks data, write "Data pending — to be supplemented" rather than making up numbers.
- Preserve original company names, technology names, region names, and metrics exactly as they appear in the source context.
- This is a {deck_type}. Prioritize information density over visual flair.

【Deck Plan — Slide Structure】
{plan_summary}

【Per-Slide Source Context — USE THIS, DO NOT SUMMARIZE】
{context_blocks}

【Generation Rules — CRITICAL, READ CAREFULLY】
1. Each slide MUST be based on its corresponding source_context block above. Do not generate from global memory or general knowledge.
2. Preserve original data: company names, technology names, region names, and metrics (%, $, CAGR, market size, years) MUST appear verbatim from the source_context.
3. If a slide's source_context is sparse or lacks specific data, display "Data pending — to be supplemented" rather than inventing plausible-sounding numbers.
4. Keep the deck plan structure: slide titles, goals, key_points, and preferred_layout are provided as guidance. You may adjust layout but keep the content structure.
5. Include keyboard navigation (arrow keys, space), theme switching (dropdown or button), and speaker notes for every slide.
6. Speaker notes should explain the slide's data sources and key takeaways — reference the source_context sections.
7. For reading decks: use denser text layouts, smaller fonts for body text, larger content areas.
8. For tables detected in source_context: render them as HTML tables, not as paragraphs.
9. Output language: {language}.
10. Do NOT wrap the output — write index.html directly with the Write tool.

【How to proceed】
1. Use the Skill tool to invoke html-ppt — this will give you the templates and guidance.
2. Read the html-ppt skill templates and assets from .agents/skills/html-ppt/ to understand available themes and layouts.
3. Generate the presentation following the deck plan and using the source_context for each slide.
4. Use the Write tool to create index.html at the output directory path.
5. Verify that key data points from source_context appear in the slides.
"""
    return prompt


def _format_deck_plan_summary(deck_plan: dict[str, Any]) -> str:
    """Format the deck plan as a concise text table for the prompt."""
    lines = []
    for slide in deck_plan.get("slides", []):
        no = slide.get("slide_no", "?")
        title = slide.get("slide_title", "")
        goal = slide.get("slide_goal", "")
        layout = slide.get("preferred_layout", "two-column")
        sources = ", ".join(slide.get("source_sections", []))
        key_pts = "; ".join(slide.get("key_points", [])[:3])

        lines.append(
            f"Slide {no}: {title}\n"
            f"  Layout: {layout} | Sources: {sources or '(cover/toc)'}\n"
            f"  Goal: {goal}\n"
            f"  Key points: {key_pts or '(see source context)'}"
        )
    return "\n\n".join(lines)


def _build_search_block(search_level: str, language: str, slide_count: int) -> str:
    if search_level == "deep":
        return f"""
【Deep Research Phase — MUST complete BEFORE generating】
Conduct extensive web research and add a numbered reference page at the end.

Step 1 — Extensive Web Research (10+ searches):
- Use WebSearch to cover the topic from multiple angles:
  * Industry overview & market size (recent reports, stats, forecasts)
  * Key trends & developments in 2025-2026
  * Major players & competitive landscape
  * Recent news, mergers, regulatory changes
  * Relevant data: revenue, growth rates, market share, user numbers
  * Technology trends and patent landscape
  * Regional breakdown and dynamics
- Do at least 10-12 different searches covering the angles above
- Use WebFetch on the 5-8 most authoritative sources to extract detailed data

Step 2 — Build Citation Index:
- Track every data point and claim back to its source
- Assign each unique source a number: [1], [2], [3], etc.
- In the slides, add superscript citation markers like [1], [2] next to data points
- Create a final "References" slide (or two) at the end listing all sources:
  【References】
  [1] Source Title, Publisher/Author, Date, URL
  [2] Source Title, Publisher/Author, Date, URL
  ...

Step 3 — Generate the PPT:
- Use the Skill tool to invoke html-ppt
- Read templates from .agents/skills/html-ppt/
- Generate a {slide_count}-slide deck that INCORPORATES the research data
- The deck plan above defines the structure — integrate research findings into the planned slides
- Place citation markers [n] as superscript next to each data point from research
- The last 1-2 slides should be the References page
"""
    elif search_level == "light":
        return """
【Light Research Phase — 5-6 targeted searches along report structure】
Do 5-6 targeted web searches following the report's key themes.

Step 1 — Targeted Searches (5-6 searches):
- Read the report content and identify 5-6 key themes or claims
- Use WebSearch for exactly 5-6 targeted searches, one per key theme
- Focus on finding the most important recent (2025-2026) data points:
  * Market size / growth rate for the main market
  * 1-2 key player updates (revenue, market share, recent moves)
  * 1-2 technology or regulatory developments
  * 1 recent news item or trend shift
- Use WebFetch on 1-2 most authoritative sources for deeper data extraction

Step 2 — Integrate Findings:
- Supplement the user's content with the verified data points
- If a user-provided number is outdated, note the newer figure
- Do NOT add a full reference page — just mention sources briefly in speaker notes

Step 3 — Generate the PPT:
- Use the Skill tool to invoke html-ppt
- Generate the presentation using the enriched content and the deck plan above
- Note research sources briefly in speaker notes where data was added
"""
    else:
        return """
【No Web Research】
Use ONLY the report content provided by the user. Do not search the web.
- Base all slides on the user's content, data, and structure.
- Do not fabricate or supplement data with external knowledge.
- If the content lacks specific data, use "Data pending" rather than guessing.
"""


def _format_context_blocks(packed_context: dict[str, Any]) -> str:
    """Format per-slide source context blocks for the prompt."""
    blocks = []
    for slide in packed_context.get("slides", []):
        no = slide.get("slide_no", "?")
        title = slide.get("slide_title", "")
        ctx_list = slide.get("source_context", [])

        ctx_parts = []
        for ctx in ctx_list:
            excerpt = ctx.get("excerpt", "")
            ctx_parts.append(
                f"[Section: {ctx.get('title', '')} (ID: {ctx.get('section_id', '')})]\n"
                f"{excerpt}"
            )

        blocks.append(
            f"=== Slide {no}: {title} ===\n"
            f"{chr(10).join(ctx_parts) if ctx_parts else '(No specific context — generate from deck plan)'}"
        )

    return "\n\n".join(blocks)
