"""Package-theft temporal state machine.

Theft decisions are made from YOLO detections + temporal rules only.
Qwen is used later to enrich descriptions after a theft is confirmed.

Includes the wire helpers (`save_best_frame`, `upload_frame_to_action_router`,
`trigger_theft_alert`) the engine calls on a confirmed theft. The action
router lives on a separate Mac and is reached through ngrok via
`ACTION_ROUTER_BASE_URL`.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import requests


log = logging.getLogger("vision_pipeline.theft_tracker")


STATE_IDLE = "IDLE"
STATE_PACKAGE_ANCHORED = "PACKAGE_ANCHORED"
STATE_PERSON_PRESENT = "PERSON_PRESENT"
STATE_PACKAGE_MOVED_OR_MISSING = "PACKAGE_MOVED_OR_MISSING"
STATE_THEFT_CONFIRMED = "THEFT_CONFIRMED"


# Frames are written under <repo>/media/frames so they live on the same disk
# as Aditya's action_router MEDIA_DIR uses on its own machine. The /upload
# endpoint copies them onto the router's local fs and returns the absolute
# path to use as `clip_path`.
_BEST_FRAME_DIR = Path(__file__).resolve().parent.parent / "media" / "frames"


def save_best_frame(frame_bgr: np.ndarray, incident_id: str) -> Path:
    """Persist the canonical 'this is the suspect' frame for an incident.

    Called once per incident at THEFT_CONFIRMED. JPEG-encodes at quality 92
    and returns the local path. The action router will pull this off disk
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


@dataclass(frozen=True)
class TheftDecision:
    state: str
    should_emit: bool
    cues: list[str]
    anchor_label: str | None = None
    anchor_box: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PackageDetection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]


def _box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _box_diag(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return (w * w + h * h) ** 0.5


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / union


def _center_dist(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay = _box_center(a)
    bx, by = _box_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


class PackageTheftTracker:
    def __init__(self, config) -> None:
        self.config = config
        self.state = STATE_IDLE

        self._pending_box: tuple[float, float, float, float] | None = None
        self._pending_label: str | None = None
        self._pending_since: float = 0.0
        self._pending_last_seen_at: float = 0.0

        self.anchor_box: tuple[float, float, float, float] | None = None
        self.anchor_label: str | None = None
        self.anchor_created_at: float = 0.0
        self.anchor_last_seen_at: float = 0.0
        self._anchor_last_box: tuple[float, float, float, float] | None = None
        self._anchor_moved_since_at: float = 0.0
        self.anchor_emitted: bool = False
        self.last_person_near_at: float = 0.0
        self.last_emit_at: float = 0.0

    def update(
        self,
        *,
        now: float,
        person_boxes: Iterable[tuple[float, float, float, float]],
        package_dets: Iterable[PackageDetection],
        feet_motion_present: bool,
    ) -> TheftDecision:
        cues: list[str] = []
        person_boxes = list(person_boxes)
        package_dets = list(package_dets)

        matched = self._match_anchor(package_dets)
        if self.anchor_box is None:
            self._maybe_build_anchor(now, package_dets)
        else:
            if matched is not None:
                self.anchor_last_seen_at = now
                reference_box = self.anchor_box
                shift = _center_dist(reference_box, matched.box)
                iou = _box_iou(reference_box, matched.box)
                if shift > self.config.move_px or iou < self.config.move_iou:
                    if self._anchor_moved_since_at <= 0.0:
                        self._anchor_moved_since_at = now
                    self.state = STATE_PACKAGE_MOVED_OR_MISSING
                    cues.append("package_moved")
                else:
                    self._anchor_moved_since_at = 0.0
                    self.state = STATE_PACKAGE_ANCHORED
                self._anchor_last_box = matched.box
            elif (now - self.anchor_last_seen_at) > self.config.package_missing_grace_seconds:
                if self._anchor_moved_since_at <= 0.0:
                    self._anchor_moved_since_at = now
                self.state = STATE_PACKAGE_MOVED_OR_MISSING
                cues.append("package_missing")

        person_present = bool(person_boxes) or (
            self.config.feet_motion_enable and feet_motion_present
        )
        person_near = self._person_near_anchor(person_boxes) or (
            self.config.feet_motion_enable and feet_motion_present and self.anchor_box is not None
        )
        if person_present:
            cues.append("person_present")
        if person_near:
            self.last_person_near_at = now
            cues.append("person_near_anchor")
            if self.state == STATE_PACKAGE_ANCHORED:
                self.state = STATE_PERSON_PRESENT

        should_emit = False
        if self.state == STATE_PACKAGE_MOVED_OR_MISSING and not self.anchor_emitted:
            person_recent = (
                self.last_person_near_at > 0.0
                and (now - self.last_person_near_at) <= self.config.interaction_window_seconds
            )
            if person_recent:
                cooldown_ok = (now - self.last_emit_at) >= self.config.theft_cooldown_seconds
                if cooldown_ok:
                    should_emit = True
                    self.state = STATE_THEFT_CONFIRMED
                    self.anchor_emitted = True
                    self.last_emit_at = now
                    cues.append("theft_confirmed")

        if self.anchor_box is not None and not should_emit:
            stale_seconds = now - self.anchor_last_seen_at
            if matched is None and stale_seconds > max(
                self.config.package_missing_grace_seconds,
                self.config.person_near_package_window_seconds,
                self.config.interaction_window_seconds,
            ):
                self._clear_anchor()
            elif self.state == STATE_PACKAGE_MOVED_OR_MISSING:
                person_stale = (
                    self.last_person_near_at <= 0.0
                    or (now - self.last_person_near_at) > self.config.interaction_window_seconds
                )
                moved_seconds = (
                    now - self._anchor_moved_since_at
                    if self._anchor_moved_since_at > 0.0
                    else 0.0
                )
                if (
                    person_stale
                    and matched is not None
                    and moved_seconds > self.config.interaction_window_seconds
                ):
                    self._set_anchor(now, matched)
                elif person_stale and stale_seconds > self.config.interaction_window_seconds:
                    self._clear_anchor()

        return TheftDecision(
            state=self.state,
            should_emit=should_emit,
            cues=cues,
            anchor_label=self.anchor_label,
            anchor_box=self.anchor_box,
        )

    def _maybe_build_anchor(self, now: float, package_dets: list[PackageDetection]) -> None:
        if not package_dets:
            if (
                self._pending_box is not None
                and (now - self._pending_last_seen_at)
                <= self.config.package_missing_grace_seconds
            ):
                self.state = STATE_IDLE
                return
            self._clear_pending()
            self.state = STATE_IDLE
            return

        strongest = max(package_dets, key=lambda d: d.confidence)
        if self._pending_box is None:
            self._pending_box = strongest.box
            self._pending_label = strongest.label
            self._pending_since = now
            self._pending_last_seen_at = now
            self.state = STATE_IDLE
            return

        shift = _center_dist(self._pending_box, strongest.box)
        if shift > (self.config.move_px * 0.5):
            self._pending_box = strongest.box
            self._pending_label = strongest.label
            self._pending_since = now
            self._pending_last_seen_at = now
            self.state = STATE_IDLE
            return

        self._pending_last_seen_at = now
        if (now - self._pending_since) >= self.config.anchor_seconds:
            self._set_anchor(now, strongest)

    def _match_anchor(self, package_dets: list[PackageDetection]) -> PackageDetection | None:
        if self.anchor_box is None or not package_dets:
            return None
        match_box = self._anchor_last_box or self.anchor_box
        return min(package_dets, key=lambda d: _center_dist(match_box, d.box))

    def _person_near_anchor(self, person_boxes: list[tuple[float, float, float, float]]) -> bool:
        if self.anchor_box is None or not person_boxes:
            return False
        anchor_diag = _box_diag(self.anchor_box)
        if anchor_diag <= 1.0:
            anchor_diag = 40.0
        for p in person_boxes:
            if _box_iou(p, self.anchor_box) > 0.0:
                return True
            if _center_dist(p, self.anchor_box) <= (2.5 * anchor_diag):
                return True
        return False

    def _clear_anchor(self) -> None:
        self.anchor_box = None
        self.anchor_label = None
        self.anchor_created_at = 0.0
        self.anchor_last_seen_at = 0.0
        self._anchor_last_box = None
        self._anchor_moved_since_at = 0.0
        self.anchor_emitted = False
        self.last_person_near_at = 0.0
        self._clear_pending()
        self.state = STATE_IDLE

    def _set_anchor(self, now: float, det: PackageDetection) -> None:
        self.anchor_box = det.box
        self.anchor_label = det.label
        self.anchor_created_at = now
        self.anchor_last_seen_at = now
        self._anchor_last_box = det.box
        self._anchor_moved_since_at = 0.0
        self.anchor_emitted = False
        self._clear_pending()
        self.state = STATE_PACKAGE_ANCHORED

    def _clear_pending(self) -> None:
        self._pending_box = None
        self._pending_label = None
        self._pending_since = 0.0
        self._pending_last_seen_at = 0.0
