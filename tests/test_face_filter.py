"""Tests for the face-recognition exclusion layer.

These tests inject a deterministic stub embedder so they run without the heavy
InsightFace / ONNX runtime dependency. The stub paints "ID tags" at the
top-left of each painted person box; when called on a full BGR frame it scans
for tag pixels and returns one FaceEmbedding per tag — letting us exercise
the filter end-to-end with frame-coordinate face boxes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vision_pipeline.face_filter import (
    FaceEmbedding,
    FaceFilter,
    save_database,
)

# ---------------------------------------------------------------------------
# Test fixtures + helpers
# ---------------------------------------------------------------------------


# Three orthogonal "embeddings" used as ground truth in the stub. Cosine
# similarity of an embedding with itself is 1.0; with any other it's 0.0.
EMB_AMISH = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
EMB_PARENT = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
EMB_STRANGER = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
EMB_OFFSET = np.array([0.6, 0.0, 0.8, 0.0], dtype=np.float32)  # close-ish to AMISH


def _tagged_frame(
    width: int = 640,
    height: int = 480,
    *,
    boxes: list[tuple[tuple[float, float, float, float], np.ndarray, int]] | None = None,
) -> tuple[np.ndarray, list[tuple[float, float, float, float]]]:
    """Build a frame containing painted ID tags inside given person boxes.

    Each box entry is `(person_box, embedding_to_emit, tag_size_px)`. The
    StubEmbedder reads tag id / size from a single pixel near the top-left of
    each person box and emits one FaceEmbedding in FRAME coordinates anchored
    at that pixel, of size `tag_size_px`.
    """
    boxes = boxes or []
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    person_boxes: list[tuple[float, float, float, float]] = []
    for person_box, embedding, tag_size in boxes:
        x1, y1, x2, y2 = (int(v) for v in person_box)
        tag_id = _embedding_id(embedding)
        # Paint the tag at the top-left corner of the person box.
        # Channel 0 = embedding id (1..255), channel 1 = tag size in pixels.
        frame[y1, x1, 0] = tag_id
        frame[y1, x1, 1] = min(255, max(1, tag_size))
        person_boxes.append((float(x1), float(y1), float(x2), float(y2)))
    return frame, person_boxes


_KNOWN_EMBEDDINGS_BY_ID: dict[int, np.ndarray] = {}


def _embedding_id(embedding: np.ndarray) -> int:
    """Stable, small int identifier for an embedding (1..255)."""
    key = embedding.tobytes()
    for existing_id, existing_emb in _KNOWN_EMBEDDINGS_BY_ID.items():
        if existing_emb.tobytes() == key:
            return existing_id
    new_id = len(_KNOWN_EMBEDDINGS_BY_ID) + 1
    if new_id > 255:
        raise RuntimeError("Too many distinct embeddings in test fixtures")
    _KNOWN_EMBEDDINGS_BY_ID[new_id] = embedding.copy()
    return new_id


class StubEmbedder:
    """Deterministic full-frame embedder used by tests.

    Scans the frame for non-zero channel-0 pixels (painted tags) and returns
    one FaceEmbedding per tag, in frame coordinates. The face bbox starts at
    the tagged pixel and extends `tag_size` pixels to the right and down so
    the face center reliably falls inside the parent person box.
    """

    def detect_and_embed(self, bgr_image: np.ndarray) -> list[FaceEmbedding]:
        if bgr_image is None or bgr_image.size == 0:
            return []
        if bgr_image.ndim < 3:
            return []
        ys, xs = np.nonzero(bgr_image[:, :, 0])
        out: list[FaceEmbedding] = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            tag_id = int(bgr_image[y, x, 0])
            tag_size = int(bgr_image[y, x, 1]) or 80
            embedding = _KNOWN_EMBEDDINGS_BY_ID.get(tag_id)
            if embedding is None:
                continue
            bbox = (float(x), float(y), float(x + tag_size), float(y + tag_size))
            out.append(FaceEmbedding(bbox=bbox, embedding=embedding.astype(np.float32)))
        return out


@pytest.fixture
def family_db(tmp_path: Path) -> Path:
    """Write a 2-person database (amish + parent)."""
    db = tmp_path / "embeddings.json"
    save_database(db, {"amish": [EMB_AMISH], "parent": [EMB_PARENT]})
    return db


@pytest.fixture
def make_filter(family_db: Path):
    def _make(**overrides) -> FaceFilter:
        kwargs = dict(
            db_path=family_db,
            similarity_threshold=0.45,
            min_face_pixels=40,
            embedder=StubEmbedder(),
        )
        kwargs.update(overrides)
        return FaceFilter(**kwargs)

    return _make


# ---------------------------------------------------------------------------
# Required test cases
# ---------------------------------------------------------------------------


def test_known_face_suppresses(make_filter):
    filt = make_filter()
    person_box = (100.0, 100.0, 300.0, 500.0)
    frame, boxes = _tagged_frame(boxes=[(person_box, EMB_AMISH, 80)])

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is True
    assert len(verdicts) == 1
    assert verdicts[0].name == "amish"
    assert verdicts[0].similarity == pytest.approx(1.0, rel=1e-3)
    assert verdicts[0].reason == "known"


def test_unknown_face_does_not_suppress(make_filter):
    filt = make_filter()
    person_box = (100.0, 100.0, 300.0, 500.0)
    frame, boxes = _tagged_frame(boxes=[(person_box, EMB_STRANGER, 80)])

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert verdicts[0].name is None
    assert verdicts[0].reason == "unknown"


def test_mixed_scene_does_not_suppress(make_filter):
    """Family + stranger together must still fire — the stranger is the threat."""
    filt = make_filter()
    family_box = (50.0, 50.0, 200.0, 400.0)
    stranger_box = (300.0, 50.0, 450.0, 400.0)
    frame, boxes = _tagged_frame(
        boxes=[
            (family_box, EMB_AMISH, 80),
            (stranger_box, EMB_STRANGER, 80),
        ]
    )

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert {v.name for v in verdicts} == {"amish", None}
    unknown = next(v for v in verdicts if v.name is None)
    assert unknown.reason == "unknown"


def test_face_too_small_falls_through_to_classification(make_filter):
    """A face smaller than min_face_pixels must NOT be treated as known."""
    filt = make_filter(min_face_pixels=60)
    person_box = (100.0, 100.0, 300.0, 500.0)
    # Tag size below threshold (40 px short edge < 60 px min).
    frame, boxes = _tagged_frame(boxes=[(person_box, EMB_AMISH, 40)])

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert verdicts[0].is_known is False
    assert verdicts[0].reason == "face_too_small"


# ---------------------------------------------------------------------------
# Bonus coverage that protects the public contract
# ---------------------------------------------------------------------------


def test_no_face_detected_falls_through(make_filter):
    """Person visible but face not detectable (back of head etc.)."""
    filt = make_filter()
    # Frame with no painted tag = stub returns zero faces.
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    boxes = [(100.0, 100.0, 300.0, 500.0)]

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert verdicts[0].reason == "no_face"


def test_no_persons_returns_no_suppression(make_filter):
    """all_known([]) must return (False, []) — nothing to suppress."""
    filt = make_filter()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    suppress, verdicts = filt.all_known(frame, [])
    assert suppress is False
    assert verdicts == []


def test_borderline_similarity_below_threshold_is_unknown(make_filter):
    """An embedding similar to but below threshold must not match."""
    filt = make_filter(similarity_threshold=0.9)
    person_box = (100.0, 100.0, 300.0, 500.0)
    frame, boxes = _tagged_frame(boxes=[(person_box, EMB_OFFSET, 80)])

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert verdicts[0].name is None
    # Similarity should be > 0 (not orthogonal) but below the 0.9 threshold.
    assert 0.0 < verdicts[0].similarity < 0.9


def test_overlapping_yolo_boxes_collapse_to_one_verdict(make_filter):
    """YOLO multi-detection: 5 overlapping boxes for one person => 1 verdict.

    Without dedup, the filter would need ALL 5 boxes to match family — but
    only the largest would actually contain the face. This is the regression
    test that proved the filter never suppressed in real demos.
    """
    filt = make_filter()
    primary = (100.0, 100.0, 300.0, 500.0)
    duplicates = [
        (105.0, 102.0, 303.0, 502.0),
        (110.0, 105.0, 305.0, 505.0),
        (95.0, 98.0, 295.0, 495.0),
        (108.0, 99.0, 299.0, 498.0),
    ]
    frame, _ = _tagged_frame(boxes=[(primary, EMB_AMISH, 80)])
    # Only the primary has a tag painted; the duplicates are bare boxes.
    all_boxes = [primary, *duplicates]

    suppress, verdicts = filt.all_known(frame, all_boxes)

    assert suppress is True
    assert len(verdicts) == 1  # 5 overlapping boxes => 1 verdict
    assert verdicts[0].name == "amish"


def test_full_frame_face_detection_runs_once(make_filter):
    """Six person boxes for one person => one detect_and_embed call."""
    filt = make_filter()
    primary = (100.0, 100.0, 300.0, 500.0)
    duplicates = [(p, p, p, p) for p in []]  # placeholder; build below
    duplicates = [
        (105 + i, 100 + i, 305 + i, 500 + i)
        for i in range(5)
    ]
    frame, _ = _tagged_frame(boxes=[(primary, EMB_AMISH, 80)])

    counts = {"n": 0}
    inner = filt._embedder.detect_and_embed

    def counting(image):
        counts["n"] += 1
        return inner(image)

    filt._embedder.detect_and_embed = counting  # type: ignore[assignment]

    filt.all_known(frame, [primary, *duplicates])

    assert counts["n"] == 1


def test_empty_database_treats_everyone_as_unknown(tmp_path: Path):
    """Filter with no enrolled people must never suppress."""
    empty_db = tmp_path / "empty.json"
    filt = FaceFilter(db_path=empty_db, embedder=StubEmbedder())
    person_box = (100.0, 100.0, 300.0, 500.0)
    frame, boxes = _tagged_frame(boxes=[(person_box, EMB_AMISH, 80)])

    suppress, verdicts = filt.all_known(frame, boxes)

    assert suppress is False
    assert verdicts[0].is_known is False


def test_save_database_appends_for_existing_name(tmp_path: Path):
    """Re-running enrollment for the same person must merge embeddings."""
    db = tmp_path / "embeddings.json"
    save_database(db, {"amish": [EMB_AMISH]})
    save_database(db, {"amish": [EMB_OFFSET]})

    filt = FaceFilter(db_path=db, embedder=StubEmbedder())
    assert filt.enrolled_names == ["amish"]
    only_person = filt._known[0]
    assert only_person.embeddings.shape[0] == 2
