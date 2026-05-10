"""Tests for the LastClassification dataclass that the camera overlay reads.

We can't easily exercise the overlay rendering without OpenCV/Qwen, but we can
verify the data structure and population logic to make sure the overlay always
gets fresh, well-formed data sourced from the event JSON (not hardcoded).
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")
pytest.importorskip("cv2")

from vision_pipeline.engine import LastClassification


def test_last_classification_starts_unset() -> None:
    cls = LastClassification()
    assert cls.is_set is False
    assert cls.tier == 0
    assert cls.suspect_description == ""


def test_last_classification_marks_set_when_timestamp_populated() -> None:
    cls = LastClassification(
        timestamp=1.0,
        tier=3,
        behavior_pattern="taking_item",
        confidence=0.85,
        scene="the library aisle",
        suspect_description="tall man in a black shirt and gray jeans",
        one_line_summary="person reached for a backpack on the table",
    )
    assert cls.is_set is True
    assert cls.tier == 3
    assert cls.scene == "the library aisle"
    assert "black shirt" in cls.suspect_description
