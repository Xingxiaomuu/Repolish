import shutil
import subprocess
from pathlib import Path

from settings import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def build_prompt(request, job_dir: Path) -> str:
    """Build the prompt string that instructs Claude Code to generate a deck."""
    language = request.language.strip() if request.language else "English"
    topic = request.topic.strip() if request.topic else "Untitled Presentation"
    content = (
        request.content.strip()
        if request.content
        else "(No detailed content provided. Please generate a basic outline based on the topic.)"
    )
    style = request.style.strip() if request.style else "professional"
    audience = request.audience.strip() if request.audience else "general audience"
    extra = request.extra_requirements.strip() if request.extra_requirements else ""
    slide_count = request.slide_count if request.slide_count else 10
    search_level = request.search_level.strip() if request.search_level else "none"

    extra_lines = extra if extra else ""

    # Build search instructions based on level
    if search_level == "deep":
        search_block = """
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
  * Regional breakdown and regional dynamics
- Do at least 10-12 different searches covering the angles above
- Use WebFetch on the 5-8 most authoritative sources to extract detailed data

Step 2 — Build Citation Index:
- Track every data point and claim back to its source
- Assign each unique source a number: [1], [2], [3], etc.
- In the slides, add superscript citation markers like [1], [2] next to data points
- Create a final "References" slide at the end listing all sources:
  【References】
  [1] Source Title, Publisher/Author, Date, URL
  [2] Source Title, Publisher/Author, Date, URL
  ...

Step 3 — Generate the PPT:
- Use the Skill tool to invoke html-ppt
- Read templates from .agents/skills/html-ppt/
- Generate a {slide_count}-slide deck that INCORPORATES the research data
- Include specific numbers, growth rates, market sizes from your research
- Place citation markers [n] as superscript next to each data point that came from research
- The last 1-2 slides should be the References page
"""
    elif search_level == "light":
        search_block = """
【Light Research Phase — quick fact-check along report structure】
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
- Do NOT add a full reference page — just mention sources in speaker notes

Step 3 — Generate the PPT:
- Use the Skill tool to invoke html-ppt
- Generate the presentation using the enriched content
- Note research sources briefly in speaker notes where data was added
"""
    else:  # "none"
        search_block = """
【No Web Research】
Use ONLY the report content provided by the user. Do not search the web.
- Base all slides on the user's content, data, and structure.
- Do not fabricate or supplement data with external knowledge.
- If the content lacks specific data, use "Data pending" rather than guessing.
"""

    prompt = f"""ACT NOW — use the Skill tool immediately to invoke html-ppt. Then use Write to create the index.html file.

【Task】Generate an HTML presentation and write it to disk.

【Output Directory】You MUST write index.html and all assets to: {job_dir}

【Topic】{topic}

【Language】{language}

【Slide Count】Approximately {slide_count} slides.

【Audience】{audience}

【Style Requirements】{style}

【Extra Requirements】{extra_lines}

【Report Content】
{content}
{search_block}
【How to proceed】
1. Use the Skill tool to invoke html-ppt — this will give you the templates and guidance.
2. Read the html-ppt skill templates and assets from .agents/skills/html-ppt/ to understand available themes and layouts.
3. Use the Write tool to create index.html at the output directory path.
4. Include keyboard navigation, theme switching, and speaker notes.
5. Do NOT just describe what you would do — use the tools and write the actual files.
"""
    return prompt


def run_claude(job_dir: Path, logs_path: Path) -> int:
    """
    Run Claude Code CLI with the prompt piped via stdin.

    Writes all stdout/stderr to logs_path.
    Returns exit code: 0 on success, -1 on timeout, -2 if CLI not found.
    """
    prompt_file = job_dir / "prompt.txt"
    prompt = prompt_file.read_text(encoding="utf-8")

    # Resolve claude executable to a full path (required for subprocess on Windows)
    resolved = shutil.which(settings.claude_code_command)
    if not resolved:
        for candidate in ["claude", "claude.exe"]:
            resolved = shutil.which(candidate)
            if resolved:
                break
    if not resolved:
        with open(logs_path, "w", encoding="utf-8") as f:
            f.write(
                "Claude Code CLI not found. "
                "Install Claude Code CLI or set CLAUDE_CODE_COMMAND env var.\n"
            )
        return -2

    cmd = [resolved, "--print", "--output-format", "json", "--dangerously-skip-permissions"]

    # Write log header
    with open(logs_path, "w", encoding="utf-8") as f:
        f.write(f"Command: {' '.join(cmd)}  (prompt via stdin pipe)\n\n")
        f.write(f"Working directory (cwd): {PROJECT_ROOT}\n")
        f.write(f"Output directory: {job_dir}\n")
        f.write(f"Timeout: {settings.claude_timeout}s\n\n")
        f.write("=== STDOUT / STDERR ===\n\n")

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            timeout=settings.claude_timeout,
            encoding="utf-8",
            errors="replace",
        )

        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(f"\nExit code: {result.returncode}\n\n")
            f.write("=== STDOUT ===\n\n")
            f.write(result.stdout)
            f.write("\n\n=== STDERR ===\n\n")
            f.write(result.stderr)

        return result.returncode

    except subprocess.TimeoutExpired:
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n=== TIMEOUT after {settings.claude_timeout} seconds ===\n")
        return -1
    except FileNotFoundError:
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n=== Claude Code CLI not found at: {resolved} ===\n")
        return -2
