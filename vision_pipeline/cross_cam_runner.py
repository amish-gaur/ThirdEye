"""Per-camera ingestion runner for the cross-camera trace demo.

Decoupled from `vision_pipeline/engine.py` (which owns theft alerting and
the BehaviorTracker state machine). This runner does the minimum
required for cross-cam search:

    video frames
        → person tracker (BYTETrack via Ultralytics)
            → for every Nth frame per active track:
                ├── crop bbox
                ├── save full-res frame + 256px thumbnail
                ├── ReID embedding (OSNet via vision_pipeline.reid)
                ├── caption → tag dict (vision_pipeline.tags)
                └── upsert track + insert sample (vision_pipeline.track_store)

The tracker, ReID extractor, and captioner are injected so tests can
swap them for fakes without booting YOLO/Qwen. The default
construction (`CrossCamRunner.with_defaults`) wires in the real
implementations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from vision_pipeline.tags import parse_caption
from vision_pipeline.track_store import TrackStore

log = logging.getLogger("vision_pipeline.cross_cam_runner")

THUMBNAIL_MAX_EDGE = 256
THUMBNAIL_JPEG_QUALITY = 80
FULL_FRAME_JPEG_QUALITY = 92


# ----------------------------------------------------------------------
# Protocols (so tests can inject mocks)
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PersonDetection:
    track_id: int
    box: tuple[float, float, float, float]
    confidence: float = 0.9


class PersonTracker(Protocol):
    """Per-frame person tracker. Implementations: ultralytics YOLO.track,
    or a fake for tests."""

    def __call__(
        self, frame: np.ndarray, frame_idx: int,
    ) -> list[PersonDetection]: ...


class ReIDLike(Protocol):
    embedding_dim: int

    def embed(self, crop: np.ndarray) -> np.ndarray: ...


# Captioner is a callable: (track_id, crop_bgr) → free-form description.
# Returning "" means "no caption", which produces an empty tag dict.
# Captioners are called at most once per track (result cached) so they
# can do expensive work like a Qwen2-VL forward pass.
Captioner = Callable[[int, np.ndarray], str]


@dataclass
class RunnerConfig:
    sample_every_n: int = 10
    """Sample every Nth frame per track. Default 10 = 1 sample/sec at 10fps."""

    crop_padding: float = 0.05
    """Pad each crop by this fraction of bbox size for robustness."""

    skip_below_height_px: int = 64
    """Reject crops smaller than this; the embedding is junk anyway."""


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------


@dataclass
class CrossCamRunner:
    cam_id: str
    store: TrackStore
    media_root: Path
    tracker: PersonTracker
    reid: ReIDLike
    captioner: Captioner = field(default=lambda _tid, _crop: "")
    config: RunnerConfig = field(default_factory=RunnerConfig)
    _caption_cache: dict[int, str] = field(default_factory=dict, init=False)

    def run(self, video_path: Path) -> int:
        """Process a video end-to-end. Returns total samples written."""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(video_path)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"could not open video {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        try:
            return self._run_loop(cap, fps)
        finally:
            cap.release()

    # --- inner loop --------------------------------------------------

    def _run_loop(self, cap: "cv2.VideoCapture", fps: float) -> int:
        samples_written = 0
        # Per-track frame counter so sample_every_n is per-track, not per-cam.
        track_frame_count: dict[int, int] = {}
        track_first_ts: dict[int, float] = {}

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            ts = frame_idx / fps

            detections = self.tracker(frame, frame_idx)

            for det in detections:
                seen = track_frame_count.get(det.track_id, -1) + 1
                track_frame_count[det.track_id] = seen

                if det.track_id not in track_first_ts:
                    track_first_ts[det.track_id] = ts

                if seen % self.config.sample_every_n != 0:
                    # Still extend the track's t_end on every detection.
                    self.store.upsert_track(
                        cam_id=self.cam_id,
                        local_track_id=det.track_id,
                        t_start=track_first_ts[det.track_id],
                        t_end=ts,
                        raw_caption=None,
                    )
                    continue

                crop = self._crop(frame, det.box)
                if crop is None:
                    continue

                caption = self._cached_caption(det.track_id, crop)
                tags = parse_caption(caption)
                embedding = self.reid.embed(crop)

                frame_path, thumb_path = self._save_media(
                    frame, crop, det.track_id, frame_idx,
                )

                track_pk = self.store.upsert_track(
                    cam_id=self.cam_id,
                    local_track_id=det.track_id,
                    t_start=track_first_ts[det.track_id],
                    t_end=ts,
                    raw_caption=caption or None,
                )
                self.store.insert_sample(
                    track_id=track_pk,
                    ts=ts,
                    frame_path=str(frame_path),
                    thumb_path=str(thumb_path),
                    embedding=embedding,
                    tags=tags,
                )
                samples_written += 1

            frame_idx += 1

        log.info(
            "cross_cam_runner cam=%s frames=%d samples=%d tracks=%d",
            self.cam_id, frame_idx, samples_written, len(track_frame_count),
        )
        return samples_written

    # --- helpers -----------------------------------------------------

    def _cached_caption(self, track_id: int, crop: np.ndarray) -> str:
        cap = self._caption_cache.get(track_id)
        if cap is not None:
            return cap
        try:
            text = self.captioner(track_id, crop) or ""
        except Exception as exc:  # captioner errors must not kill ingest
            log.warning("captioner failed for track %d: %s", track_id, exc)
            text = ""
        self._caption_cache[track_id] = text
        return text

    def _crop(
        self, frame: np.ndarray, box: tuple[float, float, float, float],
    ) -> np.ndarray | None:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1
        pad_x = bw * self.config.crop_padding
        pad_y = bh * self.config.crop_padding
        cx1 = max(0, int(round(x1 - pad_x)))
        cy1 = max(0, int(round(y1 - pad_y)))
        cx2 = min(w, int(round(x2 + pad_x)))
        cy2 = min(h, int(round(y2 + pad_y)))
        if cx2 <= cx1 or cy2 <= cy1:
            return None
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < self.config.skip_below_height_px:
            return None
        return crop

    def _save_media(
        self,
        full_frame: np.ndarray,
        crop: np.ndarray,
        track_id: int,
        frame_idx: int,
    ) -> tuple[str, str]:
        rel_dir = Path(self.cam_id)
        frame_rel = rel_dir / f"frame_{track_id:06d}_{frame_idx:06d}.jpg"
        thumb_rel = rel_dir / f"thumb_{track_id:06d}_{frame_idx:06d}.jpg"
        frame_abs = self.media_root / frame_rel
        thumb_abs = self.media_root / thumb_rel
        frame_abs.parent.mkdir(parents=True, exist_ok=True)

        cv2.imwrite(
            str(frame_abs), full_frame,
            [cv2.IMWRITE_JPEG_QUALITY, FULL_FRAME_JPEG_QUALITY],
        )
        cv2.imwrite(
            str(thumb_abs), _resize_max_edge(crop, THUMBNAIL_MAX_EDGE),
            [cv2.IMWRITE_JPEG_QUALITY, THUMBNAIL_JPEG_QUALITY],
        )
        return str(frame_rel), str(thumb_rel)


def _resize_max_edge(img: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_edge:
        return img
    scale = max_edge / m
    return cv2.resize(
        img,
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA,
    )


# ----------------------------------------------------------------------
# Real default tracker (Ultralytics YOLO.track)
# ----------------------------------------------------------------------


class UltralyticsPersonTracker:
    """Adapter from Ultralytics `model.track(persist=True)` to PersonTracker.

    Each call assumes a fresh frame from the same video. The model holds
    state (track lifecycle) internally between calls. Person class id 0.
    """

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        device: str | None = None,
        confidence: float = 0.4,
    ) -> None:
        from ultralytics import YOLO  # heavy import deferred

        self._model = YOLO(model_path)
        self._device = device
        self._confidence = confidence

    def __call__(
        self, frame: np.ndarray, frame_idx: int,
    ) -> list[PersonDetection]:
        results = self._model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],  # person class
            conf=self._confidence,
            device=self._device,
            verbose=False,
        )
        out: list[PersonDetection] = []
        if not results:
            return out
        r = results[0]
        boxes = getattr(r, "boxes", None)
        if boxes is None or boxes.id is None:
            return out
        ids = boxes.id.int().cpu().numpy()
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy() if boxes.conf is not None else None
        for i, tid in enumerate(ids):
            x1, y1, x2, y2 = (float(v) for v in xyxy[i])
            out.append(
                PersonDetection(
                    track_id=int(tid),
                    box=(x1, y1, x2, y2),
                    confidence=float(conf[i]) if conf is not None else 1.0,
                )
            )
        return out


__all__ = [
    "CrossCamRunner",
    "PersonDetection",
    "PersonTracker",
    "ReIDLike",
    "RunnerConfig",
    "UltralyticsPersonTracker",
]
