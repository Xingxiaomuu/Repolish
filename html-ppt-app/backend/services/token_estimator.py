import math


def estimate_tokens(text: str | None) -> int:
    """Estimate token count from text, accounting for CJK character density.

    English / ASCII: ~4 characters per token
    CJK (Chinese / Japanese / Korean): ~1.5 characters per token
    Other Unicode scripts: ~4 characters per token

    This is deliberately a rough estimate — a replacement for blindly dividing
    by 4 regardless of language.  When real API token counts are available
    they can be stored in separate columns alongside this estimate.
    """
    if not text:
        return 0

    cjk = 0
    ascii_chars = 0
    other = 0

    for ch in text:
        cp = ord(ch)
        if cp <= 0x007F:
            ascii_chars += 1
        elif _is_cjk(cp):
            cjk += 1
        else:
            other += 1

    tokens = (
        math.ceil(ascii_chars / 4)
        + math.ceil(cjk / 1.5)
        + math.ceil(other / 4)
    )
    return tokens


_CHAR_COUNT_CACHE: dict[int, bool] = {}


def _is_cjk(cp: int) -> bool:
    """Return True for CJK Unified, Hiragana, Katakana, and Hangul code points."""
    cached = _CHAR_COUNT_CACHE.get(cp)
    if cached is not None:
        return cached

    cjk = (
        # CJK Unified Ideographs
        (0x4E00 <= cp <= 0x9FFF)
        # CJK Unified Ideographs Extension A
        or (0x3400 <= cp <= 0x4DBF)
        # CJK Unified Ideographs Extension B
        or (0x20000 <= cp <= 0x2A6DF)
        # CJK Compatibility Ideographs
        or (0xF900 <= cp <= 0xFAFF)
        # Hiragana
        or (0x3040 <= cp <= 0x309F)
        # Katakana
        or (0x30A0 <= cp <= 0x30FF)
        # Hangul Syllables
        or (0xAC00 <= cp <= 0xD7AF)
        # Hangul Jamo
        or (0x1100 <= cp <= 0x11FF)
        # Fullwidth forms (often used for CJK punctuation / latin characters)
        or (0xFF01 <= cp <= 0xFF60)
        # CJK Radicals Supplement
        or (0x2E80 <= cp <= 0x2EFF)
        # CJK Symbols and Punctuation
        or (0x3000 <= cp <= 0x303F)
        # Bopomofo
        or (0x3100 <= cp <= 0x312F)
    )
    _CHAR_COUNT_CACHE[cp] = cjk
    return cjk
