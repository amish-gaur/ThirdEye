"""Encode the rolling frame buffer into an MP4 clip on theft emit.

Used by `VisionEngine` when a theft decision fires. The clip becomes evidence
attached to MMS notifications and reference material for the package
identifier + Amazon return flow downstream.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable

import cv2

log = logging.getLogger("vision_pipeline.clip_writer")

DEFAULT_FPS = 10
DEFAULT_LOOKBACK_SECONDS = 8.0


@dataclass
class WrittenClip:
    path: str
    frame_count: int
    fps: int


def select_recent(
    buffered: Iterable, lookback_seconds: float = DEFAULT_LOOKBACK_SECONDS
) -> list:
    """Return BufferedFrame entries within the last `lookback_seconds`.

    Accepts any iterable of objects with `.timestamp` and `.frame_bgr` so
    callers can pass an `engine.frame_buffer` deque without coupling.
    """
    items = list(buffered)
    if not items:
        return []
    latest_ts = items[-1].timestamp
    cutoff = latest_ts - max(0.0, lookback_seconds)
    return [b for b in items if b.timestamp >= cutoff]


def write_clip(
    buffered: Iterable,
    out_path: str,
    *,
    fps: int = DEFAULT_FPS,
    lookback_seconds: float = DEFAULT_LOOKBACK_SECONDS,
) -> WrittenClip | None:
    """Encode the last `lookback_seconds` of frames to MP4 at `out_path`.

    Returns None if the buffer was empty or encoding failed (callers fall
    back to evidence-free flow). Uses cv2.VideoWriter with mp4v — no ffmpeg
    dependency. Frames must share dimensions; we use the first frame's shape.
    """
    frames = select_recent(buffered, lookback_seconds=lookback_seconds)
    if not frames:
        return None

    first = frames[0].frame_bgr
    if first is None or not hasattr(first, "shape"):
        return None
    height, width = first.shape[:2]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    if not writer.isOpened():
        log.warning("cv2.VideoWriter failed to open %s", out_path)
        return None
    try:
        count = 0
        for buf in frames:
            frame = buf.frame_bgr
            if frame is None or frame.shape[:2] != (height, width):
                continue
            writer.write(frame)
            count += 1
    finally:
        writer.release()
    if count == 0:
        try:
            os.remove(out_path)
        except OSError:
            pass
        return None
    return WrittenClip(path=out_path, frame_count=count, fps=fps)
