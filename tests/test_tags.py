"""Tag extraction from Qwen suspect descriptions.

`vision_pipeline/tags.parse_caption` turns free-form descriptions into a
structured dict the search/MCP layer can filter on.

Schema (all fields optional, omitted when not detected):
    color_top, garment_top
    color_bottom, garment_bottom
    headwear, accessory
    build, gender

Color values are standardized (crimson → red, navy → blue) so two cameras
giving slightly different language map to the same filter.
"""

from __future__ import annotations

import pytest

from vision_pipeline.tags import (
    COLOR_NORMALIZER,
    parse_caption,
)


# --- happy path ---------------------------------------------------------


def test_full_description() -> None:
    out = parse_caption(
        "tall man in red hoodie, dark jeans, with a backpack"
    )
    assert out["garment_top"] == "hoodie"
    assert out["color_top"] == "red"
    assert out["garment_bottom"] == "jeans"
    assert out["accessory"] == "backpack"
    assert out["build"] == "tall"
    assert out["gender"] == "man"


def test_minimal_top_only() -> None:
    out = parse_caption("person in a red hoodie")
    assert out["color_top"] == "red"
    assert out["garment_top"] == "hoodie"
    assert out.get("garment_bottom") is None
    assert out.get("accessory") is None


def test_woman_with_cap() -> None:
    out = parse_caption("young woman wearing a blue jacket and black cap")
    assert out["gender"] == "woman"
    assert out["color_top"] == "blue"
    assert out["garment_top"] == "jacket"
    assert out["headwear"] == "cap"


# --- color standardization ---------------------------------------------


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("crimson", "red"),
        ("scarlet", "red"),
        ("navy", "blue"),
        ("grey", "gray"),
        ("dark", None),  # vague modifiers do NOT collapse to a color
        ("light", None),
    ],
)
def test_color_normalization(raw: str, canonical: str | None) -> None:
    assert COLOR_NORMALIZER.get(raw, raw if raw not in {"dark", "light"} else None) == canonical


def test_crimson_normalized_in_caption() -> None:
    out = parse_caption("man in crimson sweater")
    assert out["color_top"] == "red"


def test_navy_normalized_in_caption() -> None:
    out = parse_caption("person in navy jacket with backpack")
    assert out["color_top"] == "blue"
    assert out["accessory"] == "backpack"


# --- robustness ---------------------------------------------------------


def test_empty_caption_returns_empty_dict() -> None:
    out = parse_caption("")
    assert out == {}


def test_whitespace_only() -> None:
    assert parse_caption("    \n\t") == {}


def test_no_descriptors() -> None:
    """Caption with no useful tag content returns empty."""
    out = parse_caption("a thing happened")
    # build/gender/garment all absent → empty
    assert "garment_top" not in out
    assert "color_top" not in out


def test_only_vague_color_words() -> None:
    out = parse_caption("dark clothing on the porch")
    # 'dark' alone does not yield a real color; clothing is not a garment_top
    assert out.get("color_top") is None
    assert out.get("garment_top") is None


def test_does_not_crash_on_punctuation_garbage() -> None:
    # Should not raise.
    out = parse_caption("???   ,,,  -- ")
    assert isinstance(out, dict)


# --- nearest-color heuristic -------------------------------------------


def test_color_attaches_to_nearest_garment() -> None:
    """Multiple colors and garments: each color attaches to the closest garment."""
    out = parse_caption("man in red hoodie and white pants")
    assert out["color_top"] == "red"
    assert out["garment_top"] == "hoodie"
    assert out["garment_bottom"] == "pants"
    assert out["color_bottom"] == "white"


def test_t_shirt_alias() -> None:
    out = parse_caption("woman in green t-shirt")
    assert out["garment_top"] in ("tshirt", "t-shirt")  # accept either canonical form
    assert out["color_top"] == "green"


# --- accessory ---------------------------------------------------------


def test_carrying_a_bag() -> None:
    out = parse_caption("man carrying a black bag")
    assert out["accessory"] in {"bag", "backpack", "handbag"}


def test_no_accessory_when_absent() -> None:
    out = parse_caption("man in red hoodie")
    assert out.get("accessory") is None
