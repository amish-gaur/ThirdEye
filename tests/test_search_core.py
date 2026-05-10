"""Tests for search.core — the fan-in module the MCP/HTTP layer calls into.

Pipeline:
    1. tag-filter the samples table (color, garment, time, cam, ...)
    2. seeds = filter hits, grouped into "seed tracks"
    3. compute mean embedding per seed track
    4. expand: every track in DB with cosine(mean_seed, mean_track) >=
       SIMILARITY_THRESHOLD joins the cluster
    5. cluster timeline = all samples on member tracks, sorted by ts
    6. return one PersonCluster per cohesive cross-cam group
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from search.core import (
    PersonCluster,
    SIMILARITY_THRESHOLD,
    SearchEngine,
)
from vision_pipeline.track_store import EMBEDDING_DIM, TrackStore


def _norm(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def populated_store(tmp_path: Path) -> TrackStore:
    """Three people across two cameras.

    person_A: red hoodie, cam_1 + cam_2 (same person, similar embedding)
    person_B: blue jacket, cam_1 (different person, different embedding)
    person_C: red hoodie, cam_2 (DIFFERENT person also wearing red hoodie)
    """
    store = TrackStore(tmp_path / "search.db")
    rng = np.random.default_rng(42)

    base_a = _norm(rng.standard_normal(EMBEDDING_DIM))
    base_b = _norm(rng.standard_normal(EMBEDDING_DIM))
    base_c = _norm(rng.standard_normal(EMBEDDING_DIM))

    def _jitter(base: np.ndarray, scale: float = 0.01) -> np.ndarray:
        return _norm(base + scale * rng.standard_normal(EMBEDDING_DIM))

    # person_A on cam_1
    tid_a1 = store.upsert_track("cam_1", 1, 100.0, 110.0,
                                raw_caption="man in red hoodie")
    for ts in (101.0, 105.0, 109.0):
        store.insert_sample(tid_a1, ts, f"f_{ts}.jpg", f"t_{ts}.jpg",
                            _jitter(base_a),
                            {"color_top": "red", "garment_top": "hoodie"})

    # person_A on cam_2 — same embedding base, jittered
    tid_a2 = store.upsert_track("cam_2", 1, 130.0, 140.0,
                                raw_caption="tall man red hoodie")
    for ts in (131.0, 135.0, 139.0):
        store.insert_sample(tid_a2, ts, f"f_{ts}.jpg", f"t_{ts}.jpg",
                            _jitter(base_a),
                            {"color_top": "red", "garment_top": "hoodie"})

    # person_B on cam_1 — different person, blue jacket
    tid_b = store.upsert_track("cam_1", 2, 200.0, 210.0,
                               raw_caption="woman in blue jacket")
    for ts in (201.0, 205.0, 209.0):
        store.insert_sample(tid_b, ts, f"f_{ts}.jpg", f"t_{ts}.jpg",
                            _jitter(base_b),
                            {"color_top": "blue", "garment_top": "jacket"})

    # person_C on cam_2 — also wearing red hoodie, but a different person
    tid_c = store.upsert_track("cam_2", 2, 300.0, 310.0,
                               raw_caption="short kid red hoodie")
    for ts in (301.0, 305.0, 309.0):
        store.insert_sample(tid_c, ts, f"f_{ts}.jpg", f"t_{ts}.jpg",
                            _jitter(base_c),
                            {"color_top": "red", "garment_top": "hoodie"})
    return store


def test_search_returns_at_least_one_cluster(populated_store: TrackStore) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie")
    assert len(clusters) >= 1


def test_search_red_hoodie_returns_two_distinct_clusters(
    populated_store: TrackStore,
) -> None:
    """Person A and Person C both wear red hoodies but are different people.
    The search must return them as TWO separate clusters, not merged."""
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie")
    # Two distinct identities under the same tag filter must produce >= 2 clusters.
    assert len(clusters) >= 2, (
        f"Expected ≥2 clusters (person_A and person_C), got {len(clusters)}. "
        "Check SIMILARITY_THRESHOLD — too low collapses different people."
    )


def test_person_a_cluster_spans_two_cams(populated_store: TrackStore) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie")
    # Person A appears on cam_1 + cam_2. Find the cluster that covers both.
    multi_cam = [c for c in clusters if len(c.cams_seen) >= 2]
    assert len(multi_cam) >= 1, (
        f"Expected at least one cluster spanning 2 cams (person_A on cam_1 + cam_2). "
        f"Got cluster cam coverage: {[sorted(c.cams_seen) for c in clusters]}"
    )
    cluster = multi_cam[0]
    assert "cam_1" in cluster.cams_seen
    assert "cam_2" in cluster.cams_seen


def test_search_blue_does_not_return_red_clusters(
    populated_store: TrackStore,
) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="blue")
    # All returned tracks must satisfy the filter — blue only.
    for cluster in clusters:
        for sample in cluster.samples:
            assert sample.tags.get("color_top") in (None, "blue")


def test_search_with_no_seeds_returns_empty(
    populated_store: TrackStore,
) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="purple")
    assert clusters == []


def test_get_timeline_returns_ordered_samples(
    populated_store: TrackStore,
) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie")
    multi_cam = next(c for c in clusters if len(c.cams_seen) >= 2)
    timeline = eng.get_track_timeline(multi_cam.cluster_id)
    timestamps = [s.ts for s in timeline]
    assert timestamps == sorted(timestamps), "timeline must be sorted by ts"
    # Should include samples from BOTH cams
    cams = {s.cam_id for s in timeline}
    assert {"cam_1", "cam_2"}.issubset(cams)


def test_time_range_filter(populated_store: TrackStore) -> None:
    eng = SearchEngine(populated_store)
    # Person A spans 100-140; person C is at 300+. Restrict to <200.
    clusters = eng.search_people(color_top="red", garment_top="hoodie",
                                 t_max=200.0)
    for cluster in clusters:
        for sample in cluster.samples:
            assert sample.ts <= 200.0


def test_cam_filter(populated_store: TrackStore) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie",
                                 cam_ids=["cam_2"])
    # cam_2 has person_A on cam_2 + person_C. Filter restricts to cam_2 only,
    # but cluster expansion should still bring in cam_1 samples for person_A
    # via ReID similarity. Test only that something comes back, and that the
    # SEED tracks (the things that satisfied the filter directly) were on cam_2.
    assert len(clusters) >= 1
    for c in clusters:
        # cam_2 must always appear in any cluster returned (since seeds came from there)
        assert "cam_2" in c.cams_seen


def test_cluster_has_representative_thumb(
    populated_store: TrackStore,
) -> None:
    eng = SearchEngine(populated_store)
    clusters = eng.search_people(color_top="red", garment_top="hoodie")
    for cluster in clusters:
        assert cluster.representative_thumb_path  # non-empty string
        # representative thumb must be a real sample's thumb_path
        all_thumbs = {s.thumb_path for s in cluster.samples}
        assert cluster.representative_thumb_path in all_thumbs


def test_similarity_threshold_separates_distinct_identities() -> None:
    """Sanity check on the threshold itself."""
    assert 0.0 < SIMILARITY_THRESHOLD < 1.0
    # Threshold should be high enough that random vectors don't collapse.
    rng = np.random.default_rng(7)
    a = _norm(rng.standard_normal(EMBEDDING_DIM))
    b = _norm(rng.standard_normal(EMBEDDING_DIM))
    cos_random = float(np.dot(a, b))
    assert abs(cos_random) < SIMILARITY_THRESHOLD, (
        f"Random vectors should not exceed threshold; got cos={cos_random:.4f}, "
        f"threshold={SIMILARITY_THRESHOLD}"
    )


def test_list_cameras(populated_store: TrackStore) -> None:
    eng = SearchEngine(populated_store)
    cams = eng.list_cameras()
    cam_ids = {c["cam_id"] for c in cams}
    assert cam_ids == {"cam_1", "cam_2"}
    for c in cams:
        # each cam record reports time coverage
        assert "t_start" in c and "t_end" in c
        assert c["t_end"] >= c["t_start"]
