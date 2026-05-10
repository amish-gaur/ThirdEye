"""Qwen2-VL clothing captioner tests.

The captioner is the bridge from a person crop to a free-form clothing
description that `vision_pipeline.tags.parse_caption` can turn into a
filterable tag dict.

We don't load the real Qwen weights in the unit tests — that would take
~20s and ~5GB of VRAM. We test:
- the captioner caches by track id
- error paths return "" instead of raising (ingest must not die)
- prompt + post-processing math is correct against an injected fake
"""

from __future__ import annotations

import numpy as np
import pytest

from vision_pipeline.qwen_captioner import (
    QwenClothingCaptioner,
    _truncate_words,
)


class _FakeQwen:
    """In-test stand-in for the real Qwen2-VL forward pass."""

    def __init__(self, scripted: dict[int, str]) -> None:
        self.scripted = scripted
        self.call_count = 0
        self.last_crop_shape: tuple[int, ...] | None = None

    def __call__(self, crop: np.ndarray) -> str:
        self.call_count += 1
        self.last_crop_shape = crop.shape
        return self.scripted.get(self.call_count, "person of unclear appearance")


def _crop(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(256, 128, 3), dtype=np.uint8)


def test_caches_by_track_id() -> None:
    fake = _FakeQwen({1: "tall man in red hoodie"})
    cap = QwenClothingCaptioner(_describe=fake)

    out1 = cap(track_id=42, crop=_crop(1))
    out2 = cap(track_id=42, crop=_crop(2))   # different crop, same track
    out3 = cap(track_id=43, crop=_crop(3))   # different track → second call

    assert out1 == "tall man in red hoodie"
    assert out2 == out1, "captioner must cache by track id"
    assert out3 != "" and out3 is not None
    assert fake.call_count == 2


def test_returns_empty_on_qwen_error() -> None:
    def _explode(crop: np.ndarray) -> str:
        raise RuntimeError("MPS OOM")

    cap = QwenClothingCaptioner(_describe=_explode)
    out = cap(track_id=1, crop=_crop())
    assert out == "", "errors must degrade to empty caption, not raise"


def test_caption_is_truncated() -> None:
    fake = _FakeQwen({
        1: "tall older man in a bright crimson zip-up hooded sweatshirt "
           "carrying a small black canvas backpack with two side pockets "
           "wearing dark blue denim jeans and white sneakers",
    })
    cap = QwenClothingCaptioner(_describe=fake, max_words=15)
    out = cap(track_id=1, crop=_crop())
    assert len(out.split()) <= 15


def test_passes_real_bgr_crop_to_describer() -> None:
    captured: list[np.ndarray] = []

    def _capture(crop: np.ndarray) -> str:
        captured.append(crop)
        return "person in red hoodie"

    cap = QwenClothingCaptioner(_describe=_capture)
    crop = _crop()
    cap(track_id=1, crop=crop)
    assert len(captured) == 1
    np.testing.assert_array_equal(captured[0], crop)


# --- helper -------------------------------------------------------------


@pytest.mark.parametrize("text,n,expected", [
    ("a b c d e", 3, "a b c"),
    ("a b c", 5, "a b c"),
    ("", 4, ""),
    ("   spaced   words   ", 2, "spaced words"),
])
def test_truncate_words(text: str, n: int, expected: str) -> None:
    assert _truncate_words(text, n) == expected
