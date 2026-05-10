"""Parse Qwen suspect descriptions into structured tags.

The vision pipeline already produces a free-form description like
"tall man in red hoodie, dark jeans, with a backpack" via Qwen2-VL
(see `events.VISION_LANGUAGE_PROMPT`). This module turns that string
into a structured dict the search / MCP layer can filter on:

    {
      "color_top":      "red",     # canonical color (crimson → red)
      "garment_top":    "hoodie",
      "color_bottom":   None,
      "garment_bottom": "jeans",
      "headwear":       None,
      "accessory":      "backpack",
      "build":          "tall",
      "gender":         "man",
    }

Fields that aren't detected are simply omitted (not None) so callers can
do `tags.get("color_top")` and rely on truthiness.

Heuristic, not a model:
- Tokenize on word characters
- Find every color, garment, accessory, etc. by membership in curated sets
- Standardize colors via `COLOR_NORMALIZER`
- For each detected garment, the color attached to it is the closest color
  word within ~6 tokens, preferring colors that appear before the garment
- Top vs bottom is decided by the garment's own category
"""

from __future__ import annotations

import re
from typing import Iterable

# --- canonical vocabularies --------------------------------------------

# Hyphenated / multi-token aliases that should collapse to a single
# canonical token before tokenizing.
_PRE_SUBS: tuple[tuple[str, str], ...] = (
    ("t-shirt", "tshirt"),
    ("t shirt", "tshirt"),
)

CANONICAL_COLORS: frozenset[str] = frozenset({
    "red", "orange", "yellow", "green", "blue", "purple", "pink",
    "white", "black", "gray", "brown", "tan", "beige",
})

COLOR_NORMALIZER: dict[str, str] = {
    # primary aliases → canonical
    "grey": "gray",
    "crimson": "red",
    "scarlet": "red",
    "burgundy": "red",
    "maroon": "red",
    "navy": "blue",
    "khaki": "tan",
    "olive": "green",
    # already canonical (no-op entries kept for explicitness)
    **{c: c for c in CANONICAL_COLORS},
}

# 'dark' / 'light' are MODIFIERS, never returned as the color.
COLOR_MODIFIERS: frozenset[str] = frozenset({"dark", "light"})

GARMENTS_TOP: frozenset[str] = frozenset({
    "hoodie", "jacket", "coat", "shirt", "tshirt", "t-shirt",
    "sweater", "sweatshirt", "vest", "uniform", "dress",
})
GARMENTS_BOTTOM: frozenset[str] = frozenset({
    "jeans", "pants", "shorts", "skirt", "trousers",
})
GARMENTS = GARMENTS_TOP | GARMENTS_BOTTOM

HEADWEAR: frozenset[str] = frozenset({
    "hat", "cap", "beanie", "hood", "helmet",
})

ACCESSORIES: frozenset[str] = frozenset({
    "backpack", "bag", "handbag", "purse", "package", "box",
    "umbrella", "briefcase",
})

BUILDS: frozenset[str] = frozenset({
    "tall", "short", "young", "older", "elderly", "teen", "adult",
})

GENDERS: frozenset[str] = frozenset({
    "man", "woman", "male", "female", "boy", "girl", "person", "kid", "child",
})

# Plural → singular fallbacks (only the cases that actually show up in
# Qwen output and matter for filtering).
_PLURAL_MAP: dict[str, str] = {
    "hoodies": "hoodie", "jackets": "jacket", "coats": "coat",
    "shirts": "shirt", "tshirts": "tshirt",
    "sweaters": "sweater", "sweatshirts": "sweatshirt", "vests": "vest",
    "hats": "hat", "caps": "cap", "hoods": "hood",
    "men": "man", "women": "woman", "boys": "boy", "girls": "girl",
    "kids": "kid", "children": "child", "adults": "adult", "teens": "teen",
}

_TOKEN_RE = re.compile(r"[a-z]+(?:-[a-z]+)?")


def _tokenize(text: str) -> list[str]:
    """Lowercase and tokenize. Preserves hyphenated 't-shirt'."""
    if not text:
        return []
    text = text.lower()
    for src, dst in _PRE_SUBS:
        text = text.replace(src, dst)
    raw = _TOKEN_RE.findall(text)
    return [_PLURAL_MAP.get(tok, tok) for tok in raw]


def _canonical_color(token: str) -> str | None:
    """Map a raw token to a canonical color, or None if it's not a real color."""
    if token in COLOR_MODIFIERS:
        return None
    if token in COLOR_NORMALIZER:
        return COLOR_NORMALIZER[token]
    return None


def _nearest_color(
    tokens: list[str],
    target_idx: int,
    window: int = 6,
) -> str | None:
    """Find the canonical color closest to `tokens[target_idx]` within `window`.

    Prefers colors BEFORE the target (English noun-phrase order), but will
    look forward if no preceding color exists in window.
    """
    # backward scan
    for offset in range(1, window + 1):
        i = target_idx - offset
        if i < 0:
            break
        c = _canonical_color(tokens[i])
        if c is not None:
            return c
    # forward scan
    for offset in range(1, window + 1):
        i = target_idx + offset
        if i >= len(tokens):
            break
        c = _canonical_color(tokens[i])
        if c is not None:
            return c
    return None


def _first_match(tokens: Iterable[str], vocab: frozenset[str]) -> str | None:
    for t in tokens:
        if t in vocab:
            return t
    return None


def parse_caption(text: str | None) -> dict[str, str]:
    """Turn a Qwen suspect description into a structured tag dict.

    Returns a dict containing only the fields it could detect. Always safe
    to call (no exceptions on garbled input)."""
    if not text or not text.strip():
        return {}

    tokens = _tokenize(text)
    if not tokens:
        return {}

    out: dict[str, str] = {}

    # build / gender / headwear / accessory: first occurrence wins
    if (b := _first_match(tokens, BUILDS)) is not None:
        out["build"] = b
    if (g := _first_match(tokens, GENDERS)) is not None:
        out["gender"] = g
    if (hw := _first_match(tokens, HEADWEAR)) is not None:
        out["headwear"] = hw
    if (acc := _first_match(tokens, ACCESSORIES)) is not None:
        out["accessory"] = acc

    # garments: walk tokens once, attach nearest color to each
    seen_top = False
    seen_bottom = False
    for i, t in enumerate(tokens):
        if t in GARMENTS_TOP and not seen_top:
            out["garment_top"] = t
            color = _nearest_color(tokens, i)
            if color is not None:
                out["color_top"] = color
            seen_top = True
        elif t in GARMENTS_BOTTOM and not seen_bottom:
            out["garment_bottom"] = t
            color = _nearest_color(tokens, i)
            if color is not None:
                out["color_bottom"] = color
            seen_bottom = True

    return out


__all__ = [
    "parse_caption",
    "COLOR_NORMALIZER",
    "CANONICAL_COLORS",
    "GARMENTS_TOP",
    "GARMENTS_BOTTOM",
    "HEADWEAR",
    "ACCESSORIES",
    "BUILDS",
    "GENDERS",
]
