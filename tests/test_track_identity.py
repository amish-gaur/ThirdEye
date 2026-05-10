"""Tests for the track-anchored identity resolver.

Covers the architectural fix for SafeWatch's "friend bends over package"
false-alarm: once a track id has been identified once on a clean frame, the
identity must persist through subsequent frames where the face is occluded
or low-quality, until the track ends or its TTL expires.

Like the face_filter tests, we inject a deterministic stub embedder so we
don't need InsightFace installed.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
import pytest

from vision_pipeline.face_filter import FaceEmbedding, FaceFilter, save_database
from vision_pipeline.track_identity import (
    TrackIdentity,
    TrackIdentityResolver,
    _averaged_embedding,
)


# ---------------------------------------------------------------------------
# Stub embedders — full-frame face detector + simple body embedder
# ---------------------------------------------------------------------------


# Orthogonal vectors so cosine sim is exactly 1.0 with self, 0.0 with others.
EMB_AMISH = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
EMB_PARENT = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
EMB_STRANGER = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)


_KNOWN_EMBEDDINGS_BY_ID: dict[int, np.ndarray] = {}


def _embedding_id(embedding: np.ndarray) -> int:
    key = embedding.tobytes()
    for existing_id, existing_emb in _KNOWN_EMBEDDINGS_BY_ID.items():
        if existing_emb.tobytes() == key:
            return existing_id
    new_id = len(_KNOWN_EMBEDDINGS_BY_ID) + 1
    if new_id > 200:
        raise RuntimeError("Too many distinct embeddings in fixtures")
    _KNOWN_EMBEDDINGS_BY_ID[new_id] = embedding.copy()
    return new_id


def _tagged_frame(
    height: int = 480,
    width: int = 640,
    *,
    boxes: list[tuple[tuple[float, float, float, float], np.ndarray, int, float]] | None = None,
) -> tuple[np.ndarray, list[tuple[int | None, tuple[float, float, float, float]]]]:
    """Paint face tags inside person boxes; return (frame, [(track_id, box), ...]).

    Each entry: ``(box, embedding | None, tag_size_px, det_score)``. A None
    embedding paints no tag (i.e. face occluded).
    """
    boxes = boxes or []
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    person_boxes: list[tuple[int | None, tuple[float, float, float, float]]] = []
    for idx, (person_box, embedding, tag_size, det_score) in enumerate(boxes, start=1):
        x1, y1, x2, y2 = (int(v) for v in person_box)
        if embedding is not None:
            tag_id = _embedding_id(embedding)
            frame[y1, x1, 0] = tag_id
            frame[y1, x1, 1] = min(255, max(1, tag_size))
            # Encode det_score (0..1) into channel 2 as 1..255.
            frame[y1, x1, 2] = max(1, min(255, int(round(det_score * 255))))
        person_boxes.append((idx, (float(x1), float(y1), float(x2), float(y2))))
    return frame, person_boxes


class StubEmbedder:
    """Returns one FaceEmbedding per painted tag, in frame coordinates."""

    def detect_and_embed(self, bgr_image: np.ndarray) -> list[FaceEmbedding]:
        if bgr_image is None or bgr_image.size == 0 or bgr_image.ndim < 3:
            return []
        ys, xs = np.nonzero(bgr_image[:, :, 0])
        out: list[FaceEmbedding] = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            tag_id = int(bgr_image[y, x, 0])
            tag_size = int(bgr_image[y, x, 1]) or 80
            det_raw = int(bgr_image[y, x, 2])
            det_score = (det_raw / 255.0) if det_raw > 0 else 1.0
            embedding = _KNOWN_EMBEDDINGS_BY_ID.get(tag_id)
            if embedding is None:
                continue
            bbox = (float(x), float(y), float(x + tag_size), float(y + tag_size))
            out.append(FaceEmbedding(
                bbox=bbox,
                embedding=embedding.astype(np.float32),
                det_score=det_score,
            ))
        return out


class StubBodyEmbedder:
    """Body embedder that returns a deterministic vector per person box.

    The vector is keyed by a sentinel pixel painted at the *bottom-left* of
    the person box (channel 1 of the very last row inside the box). Tests
    use this to control which two boxes "look like the same body."
    """

    DIM = 8

    def embed(self, crop_bgr: np.ndarray) -> np.ndarray:
        if crop_bgr is None or crop_bgr.size == 0:
            return np.zeros(self.DIM, dtype=np.float32)
        # Read the sentinel byte: bottom-left pixel, channel 1.
        sentinel = int(crop_bgr[-1, 0, 1]) if crop_bgr.shape[0] >= 1 else 0
        v = np.zeros(self.DIM, dtype=np.float32)
        if sentinel == 0:
            return v
        # Map sentinel -> one-hot in DIM dims.
        v[(sentinel - 1) % self.DIM] = 1.0
        return v


def _paint_body_sentinel(
    frame: np.ndarray, box: tuple[float, float, float, float], sentinel: int
) -> None:
    """Paint a body-ReID sentinel byte at the bottom-left of the person box."""
    x1, y1, x2, y2 = (int(v) for v in box)
    if y2 - 1 < 0 or x1 < 0 or x1 >= frame.shape[1] or y2 - 1 >= frame.shape[0]:
        return
    frame[y2 - 1, x1, 1] = sentinel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def family_db(tmp_path: Path) -> Path:
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
            min_det_score=0.5,
            embedder=StubEmbedder(),
        )
        kwargs.update(overrides)
        return FaceFilter(**kwargs)

    return _make


@pytest.fixture
def make_resolver(make_filter):
    def _make(*, body: bool = False, **overrides) -> TrackIdentityResolver:
        defaults = dict(
            anchor_ttl_seconds=300.0,
            anchor_min_frames=1,            # most tests work in single-frame mode
            strong_anchor_similarity=0.55,
            body_reid_threshold=0.70,
        )
        defaults.update(overrides)
        return TrackIdentityResolver(
            make_filter(),
            body_embedder=StubBodyEmbedder() if body else None,
            **defaults,
        )

    return _make


# ---------------------------------------------------------------------------
# Track-anchored identity (the package-pickup scenario)
# ---------------------------------------------------------------------------


def test_clean_face_anchors_track(make_resolver):
    resolver = make_resolver()
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is True
    assert verdicts[0].name == "amish"
    assert verdicts[0].reason == "freshly_anchored"
    assert resolver.anchored_tracks[1].name == "amish"


def test_anchored_track_rides_through_face_occlusion(make_resolver):
    """Frame N: clean face → anchor. Frame N+1: face occluded → still suppress."""
    resolver = make_resolver()
    frame_seen, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    resolver.all_known(frame_seen, persons, now=1.0)

    # Same track id, same box, but no face painted (occluded by package etc.)
    occluded_frame, persons_again = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), None, 0, 0.0)])
    suppress, verdicts = resolver.all_known(occluded_frame, persons_again, now=1.5)

    assert suppress is True
    assert verdicts[0].name == "amish"
    assert verdicts[0].reason == "anchored"


def test_unknown_face_does_not_suppress(make_resolver):
    resolver = make_resolver()
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_STRANGER, 80, 0.95)])

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is False
    assert verdicts[0].name is None
    assert verdicts[0].reason == "unknown"


def test_mixed_family_plus_stranger_does_not_suppress(make_resolver):
    resolver = make_resolver()
    frame, persons = _tagged_frame(boxes=[
        ((50.0, 50.0, 200.0, 400.0), EMB_AMISH, 80, 0.95),
        ((300.0, 50.0, 450.0, 400.0), EMB_STRANGER, 80, 0.95),
    ])

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is False
    assert {v.name for v in verdicts} == {"amish", None}


def test_anchor_expires_after_ttl(make_resolver):
    resolver = make_resolver(anchor_ttl_seconds=10.0)
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    resolver.all_known(frame, persons, now=0.0)

    occluded, persons_again = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), None, 0, 0.0)])
    suppress, verdicts = resolver.all_known(occluded, persons_again, now=20.0)

    assert suppress is False
    assert verdicts[0].name is None
    assert verdicts[0].reason == "no_face"


def test_low_quality_face_does_not_anchor(make_resolver):
    """A low det_score face must be ignored, not falsely matched."""
    resolver = make_resolver()
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.20)])

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is False
    assert verdicts[0].name is None
    assert verdicts[0].reason == "low_quality"


def test_low_quality_face_does_not_break_existing_anchor(make_resolver):
    """Anchor on a clean frame, then receive a low-quality face — still suppress."""
    resolver = make_resolver()
    clean, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    resolver.all_known(clean, persons, now=1.0)

    bad, persons_again = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.20)])
    suppress, verdicts = resolver.all_known(bad, persons_again, now=1.5)

    assert suppress is True
    assert verdicts[0].name == "amish"


def test_face_too_small_does_not_anchor(make_resolver):
    resolver = make_resolver()
    # Tag size below default min_face_pixels=40.
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 20, 0.95)])

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is False
    assert verdicts[0].name is None


def test_anchor_min_frames_respected(make_resolver):
    """If anchor_min_frames=2 and similarity is moderate, anchor only on the second match."""
    resolver = make_resolver(anchor_min_frames=2, strong_anchor_similarity=2.0)  # never strong-anchor
    frame, persons = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])

    # First sighting: should NOT yet anchor.
    suppress_1, verdicts_1 = resolver.all_known(frame, persons, now=1.0)
    assert suppress_1 is False
    assert verdicts_1[0].reason == "freshly_anchored" or verdicts_1[0].name is None
    # Implementation note: with anchor_min_frames=2 and not-strong sim, the
    # FIRST frame returns "no anchor yet" path. With our orthogonal stub
    # embeddings sim is exactly 1.0 which is >= strong=2.0? no — 1.0 < 2.0 so
    # we do NOT strong-anchor and the count rule decides.
    assert resolver.anchored_tracks == {}

    # Second sighting: now anchor.
    suppress_2, verdicts_2 = resolver.all_known(frame, persons, now=1.1)
    assert suppress_2 is True
    assert verdicts_2[0].name == "amish"


def test_track_id_reuse_for_different_person_re_anchors(make_resolver):
    """Anchor track 1 to amish; later that same track id sees parent strongly. Drop and re-anchor."""
    resolver = make_resolver(strong_anchor_similarity=0.55)
    # Anchor as amish.
    f1, p1 = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    resolver.all_known(f1, p1, now=1.0)
    assert resolver.anchored_tracks[1].name == "amish"

    # Same track id, parent appears strongly: cosine == 1.0 with EMB_PARENT.
    f2, p2 = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_PARENT, 80, 0.95)])
    suppress, verdicts = resolver.all_known(f2, p2, now=2.0)

    assert suppress is True  # parent is also family — still suppress
    assert verdicts[0].name == "parent"


def test_no_track_id_falls_back_to_per_frame(make_resolver):
    resolver = make_resolver()
    frame, _ = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    persons = [(None, (100.0, 100.0, 300.0, 500.0))]

    suppress, verdicts = resolver.all_known(frame, persons, now=1.0)

    assert suppress is True
    assert verdicts[0].name == "amish"
    # Without a track id we cannot remember anything for next frame.
    assert resolver.anchored_tracks == {}


def test_no_persons_returns_no_suppression(make_resolver):
    resolver = make_resolver()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    suppress, verdicts = resolver.all_known(frame, [], now=1.0)
    assert suppress is False
    assert verdicts == []


# ---------------------------------------------------------------------------
# Body-ReID fallback
# ---------------------------------------------------------------------------


def test_body_reid_recovers_identity_after_track_id_switch(make_resolver):
    """Anchor track 1 to amish (with body emb). Track id 'switches' to 7
    while face is occluded — body match recovers identity."""
    resolver = make_resolver(body=True, anchor_ttl_seconds=300.0)

    # Frame 1: track 1, face visible, body sentinel = 1.
    # Box y2=470 keeps the bottom-left sentinel inside the 480-px frame.
    box1 = (100.0, 100.0, 300.0, 470.0)
    frame1, _ = _tagged_frame(boxes=[(box1, EMB_AMISH, 80, 0.95)])
    _paint_body_sentinel(frame1, box1, sentinel=1)
    persons1 = [(1, box1)]
    resolver.all_known(frame1, persons1, now=1.0)
    assert resolver.anchored_tracks[1].name == "amish"

    # Frame 2: same physical person, but ByteTrack reassigned id to 7.
    # Face occluded (no tag), body sentinel still 1 → body matches.
    box2 = (105.0, 100.0, 305.0, 470.0)
    frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
    _paint_body_sentinel(frame2, box2, sentinel=1)
    persons2 = [(7, box2)]
    suppress, verdicts = resolver.all_known(frame2, persons2, now=1.5)

    assert suppress is True
    assert verdicts[0].name == "amish"
    assert verdicts[0].reason == "body_match"


def test_body_reid_does_not_match_dissimilar_body(make_resolver):
    resolver = make_resolver(body=True)
    box1 = (100.0, 100.0, 300.0, 470.0)
    f1, _ = _tagged_frame(boxes=[(box1, EMB_AMISH, 80, 0.95)])
    _paint_body_sentinel(f1, box1, sentinel=1)
    resolver.all_known(f1, [(1, box1)], now=1.0)

    # New track 9, completely different body sentinel, no face.
    box2 = (105.0, 100.0, 305.0, 470.0)
    f2 = np.zeros((480, 640, 3), dtype=np.uint8)
    _paint_body_sentinel(f2, box2, sentinel=4)
    suppress, verdicts = resolver.all_known(f2, [(9, box2)], now=1.5)

    assert suppress is False
    assert verdicts[0].name is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_averaged_embedding_l2_normalizes():
    a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    avg = _averaged_embedding(deque([a, b], maxlen=5))
    assert np.linalg.norm(avg) == pytest.approx(1.0, rel=1e-5)


def test_track_identity_default_state():
    t = TrackIdentity(track_id=42)
    assert t.is_anchored is False
    assert t.embedding_buffer.maxlen == 5


def test_resolver_gc_drops_stale_tracks(make_resolver):
    resolver = make_resolver()
    f, p = _tagged_frame(boxes=[((100.0, 100.0, 300.0, 500.0), EMB_AMISH, 80, 0.95)])
    resolver.all_known(f, p, now=0.0)
    assert 1 in resolver._tracks

    # Tick past the GC horizon with NO sighting.
    resolver.all_known(np.zeros((480, 640, 3), dtype=np.uint8), [], now=10_000.0)
    assert 1 not in resolver._tracks
