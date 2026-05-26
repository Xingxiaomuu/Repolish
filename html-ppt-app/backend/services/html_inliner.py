"""
html_inliner.py — Converts a generated index.html into a fully self-contained
standalone.html with zero external dependencies (no CDN fonts, no file:// assets).

Strategy:
- base.css, animations.css → inline as <style>
- fonts.css → skip (system font fallback in base.css handles it)
- Theme CSS → embed all listed themes as <style data-theme="name" disabled>,
  with the current theme enabled
- runtime.js → patch applyTheme() + preview-theme handler to toggle
  <style disabled> instead of changing <link href>
- fx-runtime.js → patch FX_LIST=[] (modules pre-inlined), then inline
- All 21 fx/*.js modules → concatenate and inline as <script> tags
- <link> / <script> tags that point to local assets are removed and replaced
- All other tags (inline scripts, inline styles, meta, etc.) are preserved
"""

import re
from pathlib import Path


def _find_skill_dir() -> Path:
    """Walk up from this file's location (or cwd) until we find .agents/skills/html-ppt/."""
    candidate = Path(__file__).resolve().parent.parent.parent.parent
    skill = candidate / ".agents" / "skills" / "html-ppt"
    if skill.is_dir():
        return skill
    for p in [Path.cwd(), *Path.cwd().parents]:
        skill = p / ".agents" / "skills" / "html-ppt"
        if skill.is_dir():
            return skill
    return candidate / ".agents" / "skills" / "html-ppt"  # fallback


SKILL_DIR = _find_skill_dir()
ASSETS_DIR = SKILL_DIR / "assets"
FX_DIR = ASSETS_DIR / "animations" / "fx"

# The 21 fx module files loaded by fx-runtime.js, in the original order.
FX_MODULES = [
    "_util",
    "particle-burst", "confetti-cannon", "firework", "starfield", "matrix-rain",
    "knowledge-graph", "neural-net", "constellation", "orbit-ring", "galaxy-swirl",
    "word-cascade", "letter-explode", "chain-react", "magnetic-field", "data-stream",
    "gradient-blob", "sparkle-trail", "shockwave", "typewriter-multi", "counter-explosion",
]


def _read_skill_file(relative_path: str) -> str:
    """Read a file from the html-ppt skill assets directory."""
    path = SKILL_DIR / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Skill asset not found: {path}")
    return path.read_text(encoding="utf-8")


def _strip_google_fonts(css: str) -> str:
    """Remove Google Font family names from font stacks, keeping only system fonts.
    Google Font families to strip: Inter, Noto Sans SC, Noto Serif SC,
    JetBrains Mono, IBM Plex Mono, Playfair Display, Space Grotesk, Archivo Black.
    """
    google_families = [
        "'Inter'\\s*,?\\s*",
        "'Noto Sans SC'\\s*,?\\s*",
        "'Noto Serif SC'\\s*,?\\s*",
        "'JetBrains Mono'\\s*,?\\s*",
        "'IBM Plex Mono'\\s*,?\\s*",
        "'Playfair Display'\\s*,?\\s*",
        "'Space Grotesk'\\s*,?\\s*",
        "'Archivo Black'\\s*,?\\s*",
    ]
    for pattern in google_families:
        css = re.sub(pattern, "", css)
    return css


def _extract_current_theme(html: str) -> str:
    """Extract the current theme name from <html data-theme='...'>."""
    m = re.search(r'<html[^>]*\sdata-theme\s*=\s*["\']([^"\']+)', html)
    return m.group(1) if m else "minimal-white"


def _extract_theme_list(html: str) -> list[str]:
    """Extract the list of available themes from data-themes attribute."""
    m = re.search(r'data-themes\s*=\s*"([^"]*)"', html)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _find_asset_link_tags(html: str) -> list[dict]:
    """
    Find all <link rel="stylesheet"> tags that reference local skill assets.
    Returns list of {full_tag, href, filename}.
    """
    pattern = re.compile(
        r'<link\s[^>]*\brel\s*=\s*["\']stylesheet["\'][^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*/?>',
        re.IGNORECASE,
    )
    results = []
    for m in pattern.finditer(html):
        href = m.group(1)
        filename = href.rsplit("/", 1)[-1] if "/" in href else href
        results.append({"full_tag": m.group(0), "href": href, "filename": filename})
    return results


def _find_asset_script_tags(html: str) -> list[dict]:
    """
    Find all <script src='...'> tags that reference local skill assets.
    Returns list of {full_tag, src, filename}.
    """
    pattern = re.compile(
        r'<script\s[^>]*\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*>\s*</script>',
        re.IGNORECASE,
    )
    results = []
    for m in pattern.finditer(html):
        src = m.group(1)
        filename = src.rsplit("/", 1)[-1] if "/" in src else src
        results.append({"full_tag": m.group(0), "src": src, "filename": filename})
    return results


def _patch_runtime_js(content: str) -> str:
    """
    Patch runtime.js for standalone mode:
    1. applyTheme() → toggle <style data-theme> disabled instead of link href
    2. preview-theme handler → same approach
    """

    # Patch 1: applyTheme function
    old_apply = (
        "function applyTheme(name) {\n"
        "      let link = document.getElementById('theme-link');\n"
        "      if (!link) {\n"
        "        link = document.createElement('link');\n"
        "        link.rel = 'stylesheet';\n"
        "        link.id = 'theme-link';\n"
        "        document.head.appendChild(link);\n"
        "      }\n"
        "      link.href = themeBase + name + '.css';\n"
        "      root.setAttribute('data-theme', name);\n"
        "      const ind = document.querySelector('.theme-indicator');\n"
        "      if (ind) ind.textContent = name;\n"
        "    }"
    )
    new_apply = (
        "function applyTheme(name) {\n"
        "      document.querySelectorAll('style[data-theme]').forEach(function(s){s.disabled=true});\n"
        "      var t = document.querySelector('style[data-theme=\"'+name+'\"]');\n"
        "      if (t) t.disabled = false;\n"
        "      root.setAttribute('data-theme', name);\n"
        "      var ind = document.querySelector('.theme-indicator');\n"
        "      if (ind) ind.textContent = name;\n"
        "    }"
    )
    if old_apply in content:
        content = content.replace(old_apply, new_apply)
    else:
        # Try without the leading spaces (might have different indentation)
        raise RuntimeError(
            "Could not find applyTheme() in runtime.js — "
            "the html-ppt-skill may have been updated. "
            "Please check the runtime.js source for changes."
        )

    # Patch 2: preview-theme handler in preview mode
    old_preview = (
        "} else if (e.data.type === 'preview-theme' && e.data.name) {\n"
        "          let link = document.getElementById('theme-link');\n"
        "          if (!link) {\n"
        "            link = document.createElement('link');\n"
        "            link.rel = 'stylesheet';\n"
        "            link.id = 'theme-link';\n"
        "            document.head.appendChild(link);\n"
        "          }\n"
        "          link.href = previewThemeBase + e.data.name + '.css';\n"
        "          document.documentElement.setAttribute('data-theme', e.data.name);\n"
        "        }"
    )
    new_preview = (
        "} else if (e.data.type === 'preview-theme' && e.data.name) {\n"
        "          document.querySelectorAll('style[data-theme]').forEach(function(s){s.disabled=true});\n"
        "          var t = document.querySelector('style[data-theme=\"'+e.data.name+'\"]');\n"
        "          if (t) t.disabled = false;\n"
        "          document.documentElement.setAttribute('data-theme', e.data.name);\n"
        "        }"
    )
    if old_preview in content:
        content = content.replace(old_preview, new_preview)
    else:
        raise RuntimeError(
            "Could not find preview-theme handler in runtime.js — "
            "the html-ppt-skill may have been updated."
        )

    return content


def _patch_fx_runtime_js(content: str) -> str:
    """
    Patch fx-runtime.js for standalone mode:
    Replace FX_LIST with empty array so no dynamic script loading occurs.
    All fx modules are pre-inlined.
    """
    pattern = r"const FX_LIST = \[[\s\S]*?\];"
    replacement = "const FX_LIST = []; /* standalone: all fx modules pre-inlined */"
    new_content = re.sub(pattern, replacement, content)
    if new_content == content:
        raise RuntimeError(
            "Could not find FX_LIST in fx-runtime.js — "
            "the html-ppt-skill may have been updated."
        )
    return new_content


def _build_theme_styles(themes: list[str], current_theme: str) -> str:
    """Read all theme CSS files and return inline <style> tags.
    Google Font names are stripped from theme CSS to prevent CDN requests."""
    parts = []
    for name in themes:
        theme_css = _read_skill_file(f"assets/themes/{name}.css")
        theme_css = _strip_google_fonts(theme_css)
        disabled = "" if name == current_theme else " disabled"
        parts.append(f'<style data-theme="{name}"{disabled}>\n{theme_css}\n</style>')
    return "\n".join(parts)


def _build_fx_scripts() -> str:
    """Read all fx module JS files and return inline <script> tags."""
    parts = []
    for name in FX_MODULES:
        js_content = _read_skill_file(f"assets/animations/fx/{name}.js")
        parts.append(f"<script>\n{js_content}\n</script>")
    return "\n".join(parts)


def inline_html(job_dir: Path) -> Path:
    """
    Read index.html from job_dir, resolve all local dependencies,
    and produce a self-contained standalone.html in the same directory.

    Returns the path to the generated standalone.html.
    """
    index_path = job_dir / "index.html"
    if not index_path.is_file():
        raise FileNotFoundError(f"index.html not found in {job_dir}")

    html = index_path.read_text(encoding="utf-8")

    current_theme = _extract_current_theme(html)
    theme_list = _extract_theme_list(html)

    # ---- CSS: find and process asset <link> tags ----
    link_tags = _find_asset_link_tags(html)
    for tag_info in link_tags:
        filename = tag_info["filename"]
        if filename == "fonts.css":
            # Remove Google Fonts link entirely — base.css has system font fallbacks.
            # We strip Google Font names from base.css below so no CDN requests occur.
            replacement = ""
        elif filename == "base.css":
            css_content = _read_skill_file("assets/base.css")
            css_content = _strip_google_fonts(css_content)
            replacement = f"<style>\n{css_content}\n</style>"
        elif filename == "animations.css":
            css_content = _read_skill_file("assets/animations/animations.css")
            replacement = f"<style>\n{css_content}\n</style>"
        elif tag_info["href"] == "theme-link" or filename.endswith(".css"):
            # Theme link — will be handled separately below, remove it
            replacement = ""
        else:
            # Unknown CSS — skip (leave as-is)
            continue
        html = html.replace(tag_info["full_tag"], replacement, 1)

    # ---- CSS: inject all theme styles ----
    # Remove the original theme <link> if still present (has id="theme-link")
    theme_link_pattern = re.compile(
        r'<link\s[^>]*\bid\s*=\s*["\']theme-link["\'][^>]*/?>', re.IGNORECASE
    )
    html = theme_link_pattern.sub("", html)

    if theme_list:
        theme_styles = _build_theme_styles(theme_list, current_theme)
        # Insert theme styles after the base.css <style> tag (which replaced the base.css <link>)
        # Simple approach: inject right before </head>
        html = html.replace("</head>", theme_styles + "\n</head>", 1)

    # ---- JS: find and process asset <script> tags ----
    script_tags = _find_asset_script_tags(html)
    for tag_info in script_tags:
        filename = tag_info["filename"]
        if filename == "runtime.js":
            js_content = _read_skill_file("assets/runtime.js")
            js_content = _patch_runtime_js(js_content)
            replacement = f"<script>\n{js_content}\n</script>"
        elif filename == "fx-runtime.js":
            js_content = _read_skill_file("assets/animations/fx-runtime.js")
            js_content = _patch_fx_runtime_js(js_content)
            replacement = f"<script>\n{js_content}\n</script>"
        else:
            continue
        html = html.replace(tag_info["full_tag"], replacement, 1)

    # ---- JS: inject all fx module scripts before fx-runtime ----
    fx_scripts = _build_fx_scripts()
    # Find the fx-runtime.js inline script and insert fx modules before it
    fx_runtime_marker = "/* html-ppt :: fx-runtime.js"
    if fx_runtime_marker in html:
        html = html.replace(fx_runtime_marker, fx_scripts + "\n<script>\n" + fx_runtime_marker, 1)
    # No else: if fx-runtime isn't used in this deck, that's fine

    # ---- Clean up: remove data-theme-base attribute (not needed) ----
    html = re.sub(r'\s*data-theme-base\s*=\s*"[^"]*"', "", html)

    # ---- Write standalone.html ----
    standalone_path = job_dir / "standalone.html"
    standalone_path.write_text(html, encoding="utf-8")

    return standalone_path
