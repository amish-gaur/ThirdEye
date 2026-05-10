"""End-to-end test of the replay orchestrator.

Drops in fake trackers / fake reid / fake captioner so we don't pay
YOLO + Qwen costs in CI. Verifies that:
- multiple videos all write to the same DB
- per-cam track ids stay isolated under (cam_id, local_track_id)
- the orchestrator returns a per-cam summary
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from scripts.replay_multicam import (
    CamSpec,
    parse_video_arg,
    run_replay,
)
from vision_pipeline.cross_cam_runner import PersonDetection
from vision_pipeline.track_store import EMBEDDING_DIM, TrackStore


def _norm(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def _write_fake_video(path: Path, n_frames: int = 5) -> None:
    h, w = 240, 320
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (w, h))
    if not writer.isOpened():
        pytest.skip("cv2 cannot write mp4 in this environment")
    for i in range(n_frames):
        frame = np.full((h, w, 3), (30, 30, 30), dtype=np.uint8)
        x = 40 + i * 20
        cv2.rectangle(frame, (x, 80), (x + 60, 200), (40, 40, 200), -1)
        writer.write(frame)
    writer.release()


@dataclass
class _ScriptedTracker:
    detections_per_frame: list[list[PersonDetection]]

    def __call__(
        self, frame: np.ndarray, frame_idx: int,
    ) -> list[PersonDetection]:
        if frame_idx >= len(self.detections_per_frame):
            return []
        return self.detections_per_frame[frame_idx]


class _FakeReID:
    embedding_dim = EMBEDDING_DIM

    def __init__(self) -> None:
        self.rng = np.random.default_rng(0)

    def embed(self, crop: np.ndarray) -> np.ndarray:
        return _norm(self.rng.standard_normal(EMBEDDING_DIM))


def _captioner(track_id: int, crop: np.ndarray) -> str:
    return {
        1: "tall man in red hoodie",
        2: "woman in blue jacket",
    }.get(track_id, "person")


# --- tests -------------------------------------------------------------


def test_parse_video_arg_valid() -> None:
    spec = parse_video_arg("cam_1=path/to/foo.mp4")
    assert spec == CamSpec(cam_id="cam_1", video_path=Path("path/to/foo.mp4"))


def test_parse_video_arg_missing_equals() -> None:
    with pytest.raises(ValueError):
        parse_video_arg("path/to/foo.mp4")


def test_parse_video_arg_empty_cam_id() -> None:
    with pytest.raises(ValueError):
        parse_video_arg("=foo.mp4")


def test_run_replay_two_cams(tmp_path: Path) -> None:
    v1 = tmp_path / "cam_1.mp4"
    v2 = tmp_path / "cam_2.mp4"
    _write_fake_video(v1, n_frames=5)
    _write_fake_video(v2, n_frames=4)

    db_path = tmp_path / "tracks.db"
    media_root = tmp_path / "media"

    tracker_factory_calls: list[str] = []

    def tracker_factory(cam_id: str):
        tracker_factory_calls.append(cam_id)
        if cam_id == "cam_1":
            return _ScriptedTracker([
                [PersonDetection(track_id=1, box=(40, 80, 100, 200))]
                for _ in range(5)
            ])
        else:
            return _ScriptedTracker([
                [PersonDetection(track_id=1, box=(50, 80, 110, 200))]
                for _ in range(4)
            ])

    summary = run_replay(
        specs=[
            CamSpec(cam_id="cam_1", video_path=v1),
            CamSpec(cam_id="cam_2", video_path=v2),
        ],
        db_path=db_path,
        media_root=media_root,
        tracker_factory=tracker_factory,
        reid=_FakeReID(),
        captioner=_captioner,
        sample_every_n=1,
    )
    assert tracker_factory_calls == ["cam_1", "cam_2"]
    assert summary["total_samples"] == 9  # 5 + 4
    assert summary["per_cam"]["cam_1"]["samples"] == 5
    assert summary["per_cam"]["cam_2"]["samples"] == 4

    # Both cams in store, isolated by (cam_id, local_track_id)
    store = TrackStore(db_path)
    try:
        rows = store.search_samples()
        cam_ids = {r.cam_id for r in rows}
        assert cam_ids == {"cam_1", "cam_2"}
        # Same local_track_id (1) in both cams produces TWO different track rows.
        cam1_tracks = {r.track_id for r in rows if r.cam_id == "cam_1"}
        cam2_tracks = {r.track_id for r in rows if r.cam_id == "cam_2"}
        assert cam1_tracks.isdisjoint(cam2_tracks)
    finally:
        store.close()


def test_run_replay_skips_missing_video(tmp_path: Path) -> None:
    db_path = tmp_path / "tracks.db"
    media_root = tmp_path / "media"
    summary = run_replay(
        specs=[CamSpec(cam_id="cam_x", video_path=tmp_path / "missing.mp4")],
        db_path=db_path,
        media_root=media_root,
        tracker_factory=lambda _cid: _ScriptedTracker([]),
        reid=_FakeReID(),
        captioner=_captioner,
        sample_every_n=1,
    )
    assert summary["per_cam"]["cam_x"]["error"] is not None
    assert summary["per_cam"]["cam_x"]["samples"] == 0


def test_run_replay_continues_after_one_cam_errors(tmp_path: Path) -> None:
    """If cam_1 fails (e.g. missing video), cam_2 still runs."""
    v2 = tmp_path / "cam_2.mp4"
    _write_fake_video(v2, n_frames=3)

    summary = run_replay(
        specs=[
            CamSpec(cam_id="cam_1", video_path=tmp_path / "missing.mp4"),
            CamSpec(cam_id="cam_2", video_path=v2),
        ],
        db_path=tmp_path / "tracks.db",
        media_root=tmp_path / "media",
        tracker_factory=lambda _cid: _ScriptedTracker([
            [PersonDetection(track_id=1, box=(50, 80, 110, 200))]
            for _ in range(3)
        ]),
        reid=_FakeReID(),
        captioner=_captioner,
        sample_every_n=1,
    )
    assert summary["per_cam"]["cam_1"]["error"] is not None
    assert summary["per_cam"]["cam_2"]["samples"] == 3
    assert summary["total_samples"] == 3
