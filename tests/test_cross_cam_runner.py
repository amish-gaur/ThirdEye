"""Cross-camera ingestion runner tests.

`CrossCamRunner` is the glue that pulls frames from a video, runs YOLO
person tracking, samples every Nth frame per track, embeds with ReID,
parses captions into tags, and writes to TrackStore.

These tests use mock detectors / mock captioners so they don't depend
on YOLO weights or Qwen being available.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision_pipeline.cross_cam_runner import (
    CrossCamRunner,
    PersonDetection,
    RunnerConfig,
)
from vision_pipeline.track_store import EMBEDDING_DIM, TrackStore


# --- mock pieces -------------------------------------------------------


@dataclass
class _FakeDetection:
    track_id: int
    box: tuple[float, float, float, float]


class _FakeTracker:
    """Returns a scripted sequence of detections per frame index."""

    def __init__(self, scripted: list[list[_FakeDetection]]) -> None:
        self.scripted = scripted

    def __call__(self, frame: np.ndarray, frame_idx: int) -> list[PersonDetection]:
        if frame_idx >= len(self.scripted):
            return []
        return [
            PersonDetection(track_id=d.track_id, box=d.box, confidence=0.9)
            for d in self.scripted[frame_idx]
        ]


class _FakeReID:
    """Deterministic per-track embedding so we can assert on persistence."""

    embedding_dim = EMBEDDING_DIM

    def embed(self, crop: np.ndarray) -> np.ndarray:
        # Hash the crop's mean color to a deterministic vector.
        seed = int(crop.mean() * 1000) % 2**31
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        return v / np.linalg.norm(v)


def _captioner(track_id: int, crop: np.ndarray) -> str:
    """Map track id → canned description for tag parsing."""
    assert crop.ndim == 3, "captioner must receive an HxWx3 BGR crop"
    return {
        1: "tall man in red hoodie",
        2: "woman in blue jacket",
    }.get(track_id, "")


# --- fixtures ----------------------------------------------------------


@pytest.fixture
def fake_video(tmp_path: Path) -> Path:
    """Tiny 5-frame mp4 with a moving solid-color square."""
    path = tmp_path / "fake.mp4"
    h, w = 240, 320
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
    if not writer.isOpened():
        pytest.skip("cv2 cannot write mp4 in this environment")
    for i in range(5):
        frame = np.full((h, w, 3), (50, 50, 50), dtype=np.uint8)
        # color box at moving position
        x = 40 + i * 20
        cv2.rectangle(frame, (x, 80), (x + 60, 200), (40, 40, 200), -1)
        writer.write(frame)
    writer.release()
    return path


# --- tests -------------------------------------------------------------


def test_runner_writes_tracks_and_samples(
    tmp_path: Path, fake_video: Path,
) -> None:
    store = TrackStore(tmp_path / "tracks.db")
    media_root = tmp_path / "media"

    # Track 1 visible in frames 0,1,2,3,4. Track 2 visible in frames 2,3,4.
    scripted = [
        [_FakeDetection(1, (40, 80, 100, 200))],
        [_FakeDetection(1, (60, 80, 120, 200))],
        [_FakeDetection(1, (80, 80, 140, 200)),
         _FakeDetection(2, (200, 60, 260, 200))],
        [_FakeDetection(1, (100, 80, 160, 200)),
         _FakeDetection(2, (210, 60, 270, 200))],
        [_FakeDetection(1, (120, 80, 180, 200)),
         _FakeDetection(2, (220, 60, 280, 200))],
    ]
    runner = CrossCamRunner(
        cam_id="cam_test",
        store=store,
        media_root=media_root,
        tracker=_FakeTracker(scripted),
        reid=_FakeReID(),
        captioner=_captioner,
        config=RunnerConfig(sample_every_n=1),  # sample every frame
    )
    n_samples = runner.run(fake_video)
    assert n_samples == 8  # 5 frames × track1 + 3 frames × track2

    # Two tracks were created
    rows = store.search_samples()
    assert len({s.track_id for s in rows}) == 2

    # Track 1 has tags from "tall man in red hoodie"
    track1_samples = [s for s in rows if s.tags.get("color_top") == "red"]
    assert len(track1_samples) == 5
    for s in track1_samples:
        assert s.tags.get("garment_top") == "hoodie"
        assert s.cam_id == "cam_test"

    # Track 2 has blue/jacket tags
    track2_samples = [s for s in rows if s.tags.get("color_top") == "blue"]
    assert len(track2_samples) == 3


def test_runner_sample_every_n(tmp_path: Path, fake_video: Path) -> None:
    """sample_every_n=2 → roughly half the samples."""
    store = TrackStore(tmp_path / "tracks.db")
    scripted = [
        [_FakeDetection(1, (40, 80, 100, 200))] for _ in range(5)
    ]
    runner = CrossCamRunner(
        cam_id="cam_test",
        store=store,
        media_root=tmp_path / "media",
        tracker=_FakeTracker(scripted),
        reid=_FakeReID(),
        captioner=_captioner,
        config=RunnerConfig(sample_every_n=2),
    )
    n = runner.run(fake_video)
    # Frames 0, 2, 4 are sampled → 3 samples for track 1
    assert n == 3


def test_runner_writes_frames_and_thumbs_to_disk(
    tmp_path: Path, fake_video: Path,
) -> None:
    store = TrackStore(tmp_path / "tracks.db")
    media_root = tmp_path / "media"
    runner = CrossCamRunner(
        cam_id="cam_X",
        store=store,
        media_root=media_root,
        tracker=_FakeTracker([
            [_FakeDetection(7, (40, 80, 100, 200))],
        ]),
        reid=_FakeReID(),
        captioner=lambda _tid, _crop: "",
        config=RunnerConfig(sample_every_n=1),
    )
    runner.run(fake_video)
    rows = store.search_samples()
    assert len(rows) == 1
    s = rows[0]
    frame_abs = media_root / s.frame_path
    thumb_abs = media_root / s.thumb_path
    assert frame_abs.exists(), f"missing frame {frame_abs}"
    assert thumb_abs.exists(), f"missing thumb {thumb_abs}"
    # Thumb is smaller than the frame
    f = cv2.imread(str(frame_abs))
    t = cv2.imread(str(thumb_abs))
    assert max(t.shape[:2]) <= max(f.shape[:2])


def test_runner_handles_no_detections(tmp_path: Path, fake_video: Path) -> None:
    store = TrackStore(tmp_path / "tracks.db")
    runner = CrossCamRunner(
        cam_id="empty_cam",
        store=store,
        media_root=tmp_path / "media",
        tracker=_FakeTracker([[] for _ in range(5)]),
        reid=_FakeReID(),
        captioner=lambda _tid, _crop: "",
        config=RunnerConfig(sample_every_n=1),
    )
    n = runner.run(fake_video)
    assert n == 0
    assert store.search_samples() == []


def test_runner_extends_track_t_end(tmp_path: Path, fake_video: Path) -> None:
    store = TrackStore(tmp_path / "tracks.db")
    scripted = [
        [_FakeDetection(1, (40, 80, 100, 200))] for _ in range(5)
    ]
    runner = CrossCamRunner(
        cam_id="cam_test",
        store=store,
        media_root=tmp_path / "media",
        tracker=_FakeTracker(scripted),
        reid=_FakeReID(),
        captioner=lambda _tid, _crop: "",
        config=RunnerConfig(sample_every_n=1),
    )
    runner.run(fake_video)
    rows = store.search_samples()
    track_id = rows[0].track_id
    track = store.get_track(track_id)
    # 5 frames sampled, t_start at frame 0, t_end at frame 4
    assert track.t_end > track.t_start
