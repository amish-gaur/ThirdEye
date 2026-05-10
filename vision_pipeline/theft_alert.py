"""Theft-alert wire to the action router.

The vision pipeline calls `trigger_theft_alert(...)` once per confirmed theft.
This module owns the I/O side (frame encode + upload + tier-4 event POST) so
`theft_tracker.py` stays a pure temporal state machine.

The action router lives on a separate Mac and is reached over ngrok via the
`ACTION_ROUTER_BASE_URL` env var. See WIRING_THEFT_DETECTOR.md for the full
contract.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import requests


log = logging.getLogger("vision_pipeline.theft_alert")


# Frames are written under <repo>/media/frames so they sit on the same disk
# as the rest of the pipeline's clip output. The /upload endpoint copies them
# onto the router's local fs and returns the absolute path to use as
# `clip_path` in the event payload.
_BEST_FRAME_DIR = Path(__file__).resolve().parent.parent / "media" / "frames"


def save_best_frame(frame_bgr: np.ndarray, incident_id: str) -> Path:
    """Persist the canonical 'this is the suspect' frame for an incident.

    Called once per incident at THEFT_CONFIRMED. JPEG-encodes at quality 92
    and returns the local path. The action router pulls this off disk
    (after /upload) to attach to the iMessage fan-out.
    """
    _BEST_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    out = _BEST_FRAME_DIR / f"{incident_id}_{int(time.time())}.jpg"
    ok = cv2.imwrite(str(out), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed for {out}")
    return out


def upload_frame_to_action_router(local_path: Path) -> str:
    """POST a JPEG to /upload and return the absolute path on the router's Mac.

    The returned path is what the caller sets `clip_path` to in the /event
    POST — the action router resolves it locally to attach the frame to
    the iMessage.
    """
    base = os.environ["ACTION_ROUTER_BASE_URL"].rstrip("/")
    with local_path.open("rb") as f:
        r = requests.post(
            f"{base}/upload",
            files={"file": (local_path.name, f, "image/jpeg")},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["path"]


def trigger_theft_alert(
    *,
    frame_bgr: np.ndarray,
    incident_id: str,
    suspect_description: str,
    one_line_summary: str,
    scene: str,
    confidence: float,
    behavior_pattern: str = "taking_item",
    yolo_classes: Iterable[str] | None = None,
    time_elapsed: str = "just now",
) -> dict[str, Any]:
    """End-to-end: save best frame, upload, POST tier-4 EMERGENCY event.

    Call once per confirmed theft (idempotent on `incident_id` — the router
    dedups within 3 minutes). Returns the router's JSON receipt.
    """
    base = os.environ["ACTION_ROUTER_BASE_URL"].rstrip("/")

    frame_path = save_best_frame(frame_bgr, incident_id)
    try:
        remote_path = upload_frame_to_action_router(frame_path)
    except Exception as exc:
        log.warning("frame upload failed; firing event without attachment: %s", exc)
        remote_path = None

    payload: dict[str, Any] = {
        "tier": 4,
        "tier_name": "EMERGENCY",
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "incident_id": incident_id,
        "behavior_pattern": behavior_pattern,
        "confidence": confidence,
        "scene": scene,
        "suspect_description": suspect_description,
        "one_line_summary": one_line_summary,
        "time_elapsed": time_elapsed,
        "yolo_classes": list(yolo_classes or ["person"]),
    }
    if remote_path:
        payload["clip_path"] = remote_path

    r = requests.post(f"{base}/event", json=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    log.info("Fired theft alert: %s", body.get("actions"))
    return body
