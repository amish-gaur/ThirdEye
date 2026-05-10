"""Tests for the cross-camera track + sample persistence layer.

`vision_pipeline.track_store.TrackStore` owns SQLite WAL-mode persistence
for tracks (one per (cam, track_id) lifecycle) and samples (snapshots of a
track at a specific frame, with a ReID embedding + parsed tags).

These tests verify schema, inserts, queries, multi-writer safety, and the
filter language the search layer will rely on.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from vision_pipeline.track_store import (
    EMBEDDING_DIM,
    Sample,
    Track,
    TrackStore,
)


@pytest.fixture
def store(tmp_path: Path) -> TrackStore:
    s = TrackStore(tmp_path / "tracks.db")
    yield s
    s.close()


# --- schema -------------------------------------------------------------


def test_schema_created(store: TrackStore) -> None:
    tables = store.tables()
    assert "tracks" in tables
    assert "samples" in tables
    assert "schema_version" in tables


def test_journal_mode_is_wal(store: TrackStore) -> None:
    assert store.journal_mode().lower() == "wal"


# --- inserts ------------------------------------------------------------


def test_upsert_track_round_trip(store: TrackStore) -> None:
    track_id = store.upsert_track(
        cam_id="cam_1", local_track_id=42,
        t_start=100.0, t_end=110.0,
        raw_caption="man in red hoodie",
    )
    assert track_id > 0
    got = store.get_track(track_id)
    assert got is not None
    assert got.cam_id == "cam_1"
    assert got.local_track_id == 42
    assert got.t_start == 100.0
    assert got.t_end == 110.0
    assert got.raw_caption == "man in red hoodie"


def test_upsert_track_extends_t_end(store: TrackStore) -> None:
    """Same (cam_id, local_track_id) twice should extend the existing track."""
    tid1 = store.upsert_track("cam_1", 7, 10.0, 11.0, raw_caption="man")
    tid2 = store.upsert_track("cam_1", 7, 10.0, 15.0, raw_caption="man in red hoodie")
    assert tid1 == tid2
    got = store.get_track(tid1)
    assert got.t_end == 15.0
    assert "red hoodie" in (got.raw_caption or "")


def test_insert_sample_with_embedding(store: TrackStore) -> None:
    track_id = store.upsert_track("cam_1", 1, 0.0, 1.0)
    emb = np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(EMBEDDING_DIM)
    sample_id = store.insert_sample(
        track_id=track_id,
        ts=0.5,
        frame_path="frames/cam_1/frame_0042.jpg",
        thumb_path="thumbs/cam_1/thumb_0042.jpg",
        embedding=emb,
        tags={"color_top": "red", "garment_top": "hoodie"},
    )
    assert sample_id > 0

    samples = store.list_samples_by_track(track_id)
    assert len(samples) == 1
    s = samples[0]
    assert s.frame_path == "frames/cam_1/frame_0042.jpg"
    assert s.tags["color_top"] == "red"
    assert np.allclose(s.embedding, emb, atol=1e-6)
    assert s.embedding.dtype == np.float32


def test_embedding_must_be_correct_shape(store: TrackStore) -> None:
    track_id = store.upsert_track("cam_1", 1, 0.0, 1.0)
    bad = np.zeros(EMBEDDING_DIM - 1, dtype=np.float32)
    with pytest.raises(ValueError):
        store.insert_sample(
            track_id=track_id, ts=0.0,
            frame_path="x.jpg", thumb_path="t.jpg",
            embedding=bad, tags={},
        )


# --- queries ------------------------------------------------------------


def _seed(store: TrackStore) -> dict[str, int]:
    """Populate three tracks across two cams. Returns {label: track_id}."""
    rng = np.random.default_rng(0)
    out: dict[str, int] = {}

    # red hoodie guy on cam_1
    tid = store.upsert_track("cam_1", 1, 100.0, 110.0,
                             raw_caption="tall man in red hoodie, dark jeans")
    e1 = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    e1 /= np.linalg.norm(e1)
    store.insert_sample(tid, 105.0, "f1.jpg", "t1.jpg", e1,
                        {"color_top": "red", "garment_top": "hoodie",
                         "garment_bottom": "jeans"})
    out["A_cam1"] = tid

    # red hoodie guy on cam_2 (similar embedding for same person)
    tid = store.upsert_track("cam_2", 9, 130.0, 140.0,
                             raw_caption="tall man in red hoodie")
    e2 = e1 + 0.05 * rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    e2 /= np.linalg.norm(e2)
    store.insert_sample(tid, 135.0, "f2.jpg", "t2.jpg", e2,
                        {"color_top": "red", "garment_top": "hoodie"})
    out["A_cam2"] = tid

    # different person, blue jacket, on cam_1
    tid = store.upsert_track("cam_1", 2, 200.0, 210.0,
                             raw_caption="woman in blue jacket")
    e3 = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    e3 /= np.linalg.norm(e3)
    store.insert_sample(tid, 205.0, "f3.jpg", "t3.jpg", e3,
                        {"color_top": "blue", "garment_top": "jacket",
                         "gender": "woman"})
    out["B_cam1"] = tid
    return out


def test_query_by_color_only(store: TrackStore) -> None:
    seeded = _seed(store)
    rows = store.search_samples(color_top="red")
    track_ids = {r.track_id for r in rows}
    assert seeded["A_cam1"] in track_ids
    assert seeded["A_cam2"] in track_ids
    assert seeded["B_cam1"] not in track_ids


def test_query_by_color_and_garment(store: TrackStore) -> None:
    seeded = _seed(store)
    rows = store.search_samples(color_top="red", garment_top="hoodie")
    assert {r.track_id for r in rows} == {seeded["A_cam1"], seeded["A_cam2"]}


def test_query_by_time_range(store: TrackStore) -> None:
    seeded = _seed(store)
    rows = store.search_samples(t_min=129.0, t_max=145.0)
    assert {r.track_id for r in rows} == {seeded["A_cam2"]}


def test_query_by_cam_id(store: TrackStore) -> None:
    seeded = _seed(store)
    rows = store.search_samples(cam_ids=["cam_1"])
    assert seeded["A_cam2"] not in {r.track_id for r in rows}


def test_query_with_no_match_returns_empty(store: TrackStore) -> None:
    _seed(store)
    rows = store.search_samples(color_top="purple")
    assert rows == []


def test_load_all_embeddings(store: TrackStore) -> None:
    seeded = _seed(store)
    embs, sample_ids, track_ids = store.load_embeddings()
    assert embs.shape == (3, EMBEDDING_DIM)
    assert embs.dtype == np.float32
    assert len(sample_ids) == 3
    assert len(track_ids) == 3
    # All vectors are L2-normalized in the seed
    norms = np.linalg.norm(embs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    # Track ids returned match seeded ids
    assert set(track_ids) == set(seeded.values())


# --- multi-writer safety ------------------------------------------------


def test_concurrent_writers(tmp_path: Path) -> None:
    """Four threads writing samples simultaneously: no 'database is locked'.

    This simulates the subprocess-per-camera architecture (each subprocess
    holds its own TrackStore connection against the shared SQLite file).
    """
    db = tmp_path / "tracks.db"
    rng = np.random.default_rng(0)
    errors: list[Exception] = []

    def writer(cam_id: str, n: int) -> None:
        try:
            ts = TrackStore(db)
            try:
                for i in range(n):
                    tid = ts.upsert_track(cam_id, i,
                                          float(i), float(i) + 0.5)
                    e = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
                    e /= np.linalg.norm(e)
                    ts.insert_sample(tid, float(i), f"{cam_id}/f{i}.jpg",
                                     f"{cam_id}/t{i}.jpg", e,
                                     {"color_top": "red"})
            finally:
                ts.close()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(f"cam_{i}", 25))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert errors == [], errors

    reader = TrackStore(db)
    try:
        rows = reader.search_samples(color_top="red")
        # 4 cams × 25 samples = 100 rows
        assert len(rows) == 100
    finally:
        reader.close()
