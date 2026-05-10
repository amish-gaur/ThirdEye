"""YOLO + Qwen2-VL vision engine that emits router-compatible events.

This module is split into three layers:

* Detection layer  (`_detect_objects`): wraps YOLO with two thresholds.
* Behavior layer   (`BehaviorTracker`): pure logic that turns per-frame
  detections into a state machine with track memory, candidates, scene-clear,
  and sticky suppression. Pure-python so it is easy to unit test.
* Engine layer     (`VisionEngine`): glues capture, behavior, classifier,
  debug overlay, and failure-artifact saving together.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from ultralytics import YOLO

try:  # YOLO-World is present in recent Ultralytics builds.
    from ultralytics import YOLOWorld
except ImportError:  # pragma: no cover - depends on the installed ultralytics version
    YOLOWorld = None

from .config import CONFIG, Config
from .events import VISION_LANGUAGE_PROMPT, build_event, evaluate_classifier_output
from .face_filter import FaceFilter
from .publisher import post_event
from .theft_alert import trigger_theft_alert
from .theft_tracker import (
    PackageDetection,
    PackageTheftTracker,
    STATE_IDLE as THEFT_STATE_IDLE,
    TheftDecision,
)

FRAME_BUFFER_MAXLEN = 150
TARGET_FPS = 10
FRAME_INTERVAL_SECONDS = 1.0 / TARGET_FPS
DISPLAY_FPS = 30
DISPLAY_INTERVAL_SECONDS = 1.0 / DISPLAY_FPS
PERSON_CLASS_ID = 0
BOX_CLASS_IDS = (24, 26, 28)  # backpack, handbag, suitcase
TRIGGER_CLASS_IDS = (PERSON_CLASS_ID,) + BOX_CLASS_IDS
CONSECUTIVE_PERSON_FRAMES = 2  # legacy export, behavior uses interaction_frames_required
LABEL_ALIASES = {
    "phone": "cell phone",
    "cellphone": "cell phone",
    "mobile phone": "cell phone",
}
STRICT_OBJECT_CONFIDENCE = {
    "cell phone": 0.72,
    "laptop": 0.60,
    "handbag": 0.35,
    "suitcase": 0.35,
}

# Behavior states
STATE_IDLE = "IDLE"
STATE_WATCHING = "WATCHING"
STATE_CANDIDATE = "CANDIDATE"
STATE_SUPPRESSED = "SUPPRESSED"

log = logging.getLogger("vision_pipeline.engine")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BufferedFrame:
    timestamp: float
    frame_bgr: Any


@dataclass
class ClassificationRequest:
    timestamp: float
    frame_seq: int
    frame_bgr: Any
    yolo_classes: list[str]
    extra_frames: list[Any] = field(default_factory=list)


@dataclass
class ArtifactRequest:
    kind: str
    timestamp: float
    frame_seq: int
    frame_bgr: Any
    decision: "BehaviorDecision"
    persons: list["Detection"]
    carryables: list["Detection"]


@dataclass
class Detection:
    cls_id: int
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels


@dataclass
class TrackMemory:
    last_seen_at: float
    last_seen_in_zone_at: float = 0.0
    last_interaction_at: float = 0.0
    last_box: tuple[float, float, float, float] | None = None
    last_label: str | None = None
    anchor_box: tuple[float, float, float, float] | None = None
    stationary_since_at: float = 0.0
    removal_reported_at: float = 0.0


@dataclass
class CandidateContext:
    first_seen_at: float
    last_seen_at: float
    interaction_frames: int = 0
    recent_zone_dwell: float = 0.0
    last_zone_seen_at: float = 0.0
    last_carryable_seen_at: float = 0.0
    last_carryable_label: str | None = None
    last_person_box: tuple[float, float, float, float] | None = None
    last_carryable_box: tuple[float, float, float, float] | None = None
    last_scene_signature: str | None = None
    alert_fired: bool = False
    cues: list[str] = field(default_factory=list)


@dataclass
@dataclass
class _IdentityAnchor:
    """Sticky-by-position identity tag.

    Once the face filter recognizes a known person at high confidence and we
    see that recognition sustained for ANCHOR_CONFIRM_SECONDS, we set this
    anchor on the YOLO bounding box. From that moment on, while ANY person
    box overlaps the anchor's last-known position by IoU >= ANCHOR_IOU,
    that box inherits the anchor's identity — even if the face turns away
    (`face_too_small` / `no_face`). The anchor expires when no person box
    has overlapped it for ANCHOR_EXPIRE_SECONDS, i.e. the subject has left
    the frame entirely. This is what fixes the "Aditya turns to pick up the
    box and the alert fires anyway" failure mode.
    """
    name: str
    box: tuple[float, float, float, float]
    first_seen_at: float
    last_seen_at: float
    last_known_seen_at: float
    confirmed: bool = False


# Identity-anchor tuning. These are deliberately not in config.py because
# they shape demo-critical behavior — easier to find and tweak inline.
_ANCHOR_HIGH_CONF = 0.45             # similarity to seed an anchor
_ANCHOR_CONFIRM_SECONDS = 0.5        # sustained detection before anchor goes "live"
_ANCHOR_INHERIT_WINDOW_SECONDS = 6.0 # how long a face can be hidden and still inherit
_ANCHOR_EXPIRE_SECONDS = 8.0         # no person-box overlap this long => drop anchor
_ANCHOR_IOU = 0.30                   # IoU threshold for "same person across frames"


@dataclass
class BehaviorDecision:
    state: str
    cues: list[str]
    should_classify: bool
    suppression_active: bool
    last_emitted_at: float
    candidate: CandidateContext | None
    person_boxes: list[Detection]
    carryable_boxes: list[Detection]
    package_anchor_label: str | None = None
    package_anchor_box: tuple[float, float, float, float] | None = None
    near_miss: bool = False  # for failure-artifact saving
    # Aligned 1:1 with `person_boxes` when the face filter is enabled. Each
    # entry says "is this person known, and how confident are we?" — used by
    # the overlay to render `aditya 0.92` next to the green box, and by the
    # processing loop to suppress theft emits when every detected person is
    # enrolled. Empty list when the filter is off or no faces were detected.
    face_verdicts: list[Any] = field(default_factory=list)


@dataclass
class LastClassification:
    """Last Qwen output we successfully classified.

    Held by the engine so the camera overlay can render Qwen's live
    description / scene / behavior in real time. This is purely visual
    feedback so you can see what Qwen is saying about you while you demo.
    """
    timestamp: float = 0.0
    tier: int = 0
    behavior_pattern: str = ""
    confidence: float = 0.0
    scene: str = ""
    suspect_description: str = ""
    one_line_summary: str = ""

    @property
    def is_set(self) -> bool:
        return self.timestamp > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def require_mps() -> str:
    if not torch.backends.mps.is_available():
        raise RuntimeError(
            "MPS is not available. This script is intended for Apple Silicon "
            "with a PyTorch build that supports `.to('mps')`."
        )
    return "mps"


def frame_to_pil(frame_bgr: Any) -> Image.Image:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


def parse_capture_source(raw_source: str) -> int | str:
    """Resolve a CAMERA_SOURCE string into a `cv2.VideoCapture` argument.

    Delegates to `vision_pipeline.source_resolver` so the same logic can be
    unit-tested without touching any heavy imports. Supports the new
    `phone://` shortcuts (paired phone camera streamed via the action
    router's MJPEG endpoint) on top of the existing OpenCV inputs.
    """
    from .source_resolver import resolve_camera_source

    return resolve_camera_source(raw_source)


def _box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _box_diag(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return (w * w + h * h) ** 0.5


def _box_area(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    a_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    b_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / union


def _point_in_zone(point: tuple[float, float], zone_norm: tuple[float, float, float, float],
                   frame_size: tuple[int, int]) -> bool:
    fw, fh = frame_size
    x, y = point
    x1 = zone_norm[0] * fw
    y1 = zone_norm[1] * fh
    x2 = zone_norm[2] * fw
    y2 = zone_norm[3] * fh
    return x1 <= x <= x2 and y1 <= y <= y2


def _touches_frame_edge(
    box: tuple[float, float, float, float],
    frame_size: tuple[int, int],
    margin_ratio: float,
) -> bool:
    fw, fh = frame_size
    margin_x = fw * margin_ratio
    margin_y = fh * margin_ratio
    x1, y1, x2, y2 = box
    return x1 <= margin_x or y1 <= margin_y or x2 >= (fw - margin_x) or y2 >= (fh - margin_y)


# ---------------------------------------------------------------------------
# Behavior layer
# ---------------------------------------------------------------------------


class BehaviorTracker:
    """Pure-logic state machine used by the engine.

    All time inputs are unix timestamps. Frame size is the capture (W, H) so
    we can interpret the normalized entry zone."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state: str = STATE_IDLE
        self.cues: list[str] = []
        self.suppression_active: bool = False
        self.last_emitted_at: float = 0.0
        self.candidate: CandidateContext | None = None
        # Carryable track memory keyed by label (single-track per label is enough
        # for the demo scenario; one bag, one person).
        self.carryable_tracks: dict[str, TrackMemory] = {}
        self.person_track: TrackMemory | None = None
        self._last_frame_time: float = 0.0
        self._last_in_zone_at: float = 0.0
        self._last_no_signal_at: float = 0.0

    # --- demo-mode tuning ----------------------------------------------------

    @property
    def interaction_frames_required(self) -> int:
        base = self.config.interaction_frames_required
        if self.config.demo_mode_theft_bias:
            return max(2, base - 2)
        return base

    @property
    def min_dwell_seconds(self) -> float:
        if self.config.demo_mode_theft_bias:
            return self.config.min_dwell_seconds * 0.5
        return self.config.min_dwell_seconds

    @property
    def carryable_grace_seconds(self) -> float:
        if self.config.demo_mode_theft_bias:
            return self.config.carryable_grace_seconds * 2.0
        return self.config.carryable_grace_seconds

    @property
    def scene_clear_seconds(self) -> float:
        if self.config.demo_mode_theft_bias:
            return self.config.scene_clear_seconds * 1.5
        return self.config.scene_clear_seconds

    # --- frame ingestion -----------------------------------------------------

    def update(
        self,
        *,
        now: float,
        person_dets: list[Detection],
        carryable_dets: list[Detection],
        frame_size: tuple[int, int],
    ) -> BehaviorDecision:
        """Advance the state machine by one frame and return a decision.

        Decision tells the engine whether it should fire a classification this
        frame, plus the rendered cues/state for overlay/logging."""

        cues: list[str] = []
        zone = self.config.entry_zone

        # 1. Update track memory from raw detections
        person_in_zone_now = False
        person_candidates: list[tuple[bool, float, float, Detection]] = []
        for det in person_dets:
            in_zone = _point_in_zone(_box_center(det.box), zone, frame_size)
            if in_zone:
                person_in_zone_now = True
            person_candidates.append((in_zone, det.confidence, _box_area(det.box), det))

        primary_person: Detection | None = None
        if person_candidates:
            person_candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            primary_person = person_candidates[0][3]
            self.person_track = TrackMemory(
                last_seen_at=now,
                last_box=primary_person.box,
                last_label="person",
                last_seen_in_zone_at=now
                if _point_in_zone(_box_center(primary_person.box), zone, frame_size)
                else (self.person_track.last_seen_in_zone_at if self.person_track is not None else 0.0),
            )

        active_carryables: list[tuple[str, TrackMemory]] = []
        for det in carryable_dets:
            track_key = self._carryable_track_key(det)
            mem = self.carryable_tracks.get(track_key)
            if mem is None:
                mem = TrackMemory(
                    last_seen_at=now,
                    last_box=det.box,
                    last_label=det.label,
                    anchor_box=det.box,
                    stationary_since_at=now,
                )
            else:
                if self._box_shift_pixels(mem.anchor_box, det.box) > self.config.stationary_object_distance_pixels:
                    mem.anchor_box = det.box
                    mem.stationary_since_at = now
                mem.last_seen_at = now
                mem.last_box = det.box
                mem.last_label = det.label
                mem.anchor_box = mem.anchor_box or det.box
                if mem.stationary_since_at <= 0:
                    mem.stationary_since_at = now
                mem.removal_reported_at = 0.0
            if _point_in_zone(_box_center(det.box), zone, frame_size):
                mem.last_seen_in_zone_at = now
            self.carryable_tracks[track_key] = mem

        # 2. Determine which carryables count as "still present" (grace window)
        active_carryable_box: tuple[float, float, float, float] | None = None
        active_carryable_label: str | None = None
        active_carryable_track_key: str | None = None
        for track_key, mem in self.carryable_tracks.items():
            if (now - mem.last_seen_at) <= self.carryable_grace_seconds and mem.last_box is not None:
                active_carryables.append((track_key, mem))

        if primary_person is not None and active_carryables:
            chosen_track_key, chosen_mem = min(
                active_carryables,
                key=lambda item: self._pair_distance_score(primary_person.box, item[1].last_box),
            )
            active_carryable_box = chosen_mem.last_box
            active_carryable_label = chosen_mem.last_label
            active_carryable_track_key = chosen_track_key
        elif active_carryables:
            chosen_track_key, chosen_mem = max(active_carryables, key=lambda item: item[1].last_seen_at)
            active_carryable_box = chosen_mem.last_box
            active_carryable_label = chosen_mem.last_label
            active_carryable_track_key = chosen_track_key

        # 3. Build cues
        if person_in_zone_now:
            cues.append("person_in_zone")
        if active_carryable_label is not None:
            seen_now = any(d.label == active_carryable_label for d in carryable_dets)
            if seen_now:
                cues.append(f"carryable_present:{active_carryable_label}")
            else:
                cues.append(f"carryable_recent:{active_carryable_label}")

        # 4. Pair person + carryable
        paired = False
        if primary_person is not None and active_carryable_box is not None:
            iou = _box_iou(primary_person.box, active_carryable_box)
            person_diag = _box_diag(primary_person.box)
            cx_p, cy_p = _box_center(primary_person.box)
            cx_c, cy_c = _box_center(active_carryable_box)
            dist = ((cx_p - cx_c) ** 2 + (cy_p - cy_c) ** 2) ** 0.5
            if iou >= self.config.pair_iou_threshold and (
                person_diag <= 0 or dist <= self.config.pair_distance_ratio * person_diag
            ):
                paired = True
                cues.append("person_carryable_pair")
                if active_carryable_track_key is not None:
                    self.carryable_tracks[active_carryable_track_key].last_interaction_at = now

        removed_mem: TrackMemory | None = None
        removed_label: str | None = None
        for _, mem in sorted(
            self.carryable_tracks.items(),
            key=lambda item: item[1].last_interaction_at,
            reverse=True,
        ):
            stationary_long_enough = (
                mem.anchor_box is not None
                and mem.stationary_since_at > 0
                and (mem.last_seen_at - mem.stationary_since_at) >= self.config.stationary_object_min_seconds
            )
            recently_missing = (now - mem.last_seen_at) > self.carryable_grace_seconds
            recent_person_interaction = (
                mem.last_interaction_at > 0
                and (now - mem.last_interaction_at) <= self.config.removal_interaction_window_seconds
            )
            if (
                stationary_long_enough
                and recently_missing
                and recent_person_interaction
                and mem.removal_reported_at <= 0
            ):
                mem.removal_reported_at = now
                removed_mem = mem
                removed_label = mem.last_label
                cues.append(f"carryable_removed:{removed_label}")
                break

        # 5. Update or build candidate
        interaction_signal = (paired and person_in_zone_now) or (removed_mem is not None)
        if interaction_signal:
            if self.candidate is None:
                self.candidate = CandidateContext(
                    first_seen_at=now,
                    last_seen_at=now,
                )
            cand = self.candidate
            # Object removal should be able to fire immediately once the anchor
            # object disappears after a recent person interaction.
            if removed_mem is None and self._last_frame_time > 0:
                dt = max(0.0, min(1.0, now - self._last_frame_time))
                cand.recent_zone_dwell += dt
            cand.last_seen_at = now
            cand.last_zone_seen_at = now
            cand.last_carryable_seen_at = now
            if removed_mem is not None:
                cand.last_carryable_label = removed_label
                cand.last_person_box = (
                    primary_person.box
                    if primary_person
                    else self.person_track.last_box
                    if self.person_track is not None
                    else cand.last_person_box
                )
                cand.last_carryable_box = removed_mem.anchor_box or removed_mem.last_box
                cand.interaction_frames = max(cand.interaction_frames, self.interaction_frames_required)
                cand.recent_zone_dwell = max(cand.recent_zone_dwell, self.min_dwell_seconds)
                cand.last_scene_signature = f"{removed_label}|removed"
            else:
                cand.last_carryable_label = active_carryable_label
                cand.last_person_box = primary_person.box if primary_person else cand.last_person_box
                cand.last_carryable_box = active_carryable_box
                cand.interaction_frames += 1
                cand.last_scene_signature = f"{active_carryable_label}|inzone"
            cand.cues = list(cues)

        # 6. Determine state + suppression / scene-clear
        decision_state = self.state
        should_classify = False
        near_miss = False

        scene_clear_now = self._scene_is_clear(now, person_in_zone_now, active_carryable_label is not None)

        if self.suppression_active:
            decision_state = STATE_SUPPRESSED
            if scene_clear_now:
                self.suppression_active = False
                self.candidate = None
                decision_state = STATE_IDLE
        else:
            if self.candidate is not None and self.candidate.interaction_frames > 0:
                ready = (
                    self.candidate.interaction_frames >= self.interaction_frames_required
                    and self.candidate.recent_zone_dwell >= self.min_dwell_seconds
                )
                cooldown_ok = (now - self.last_emitted_at) >= self.config.classification_cooldown_seconds
                if ready and cooldown_ok and not self.candidate.alert_fired:
                    should_classify = True
                    self.candidate.alert_fired = True
                    self.last_emitted_at = now
                    self.suppression_active = True
                    decision_state = STATE_CANDIDATE
                else:
                    decision_state = STATE_CANDIDATE
                    # Near-miss heuristic: meaningful evidence but didn't trip
                    if (
                        self.candidate.interaction_frames >= max(2, self.interaction_frames_required // 2)
                        and self.candidate.recent_zone_dwell >= self.min_dwell_seconds * 0.5
                        and not self.candidate.alert_fired
                    ):
                        near_miss = True
            elif person_in_zone_now or active_carryable_label is not None:
                decision_state = STATE_WATCHING
            else:
                decision_state = STATE_IDLE
                # Drop stale candidate only when scene fully cleared
                if scene_clear_now:
                    self.candidate = None

        self.state = decision_state
        self.cues = cues
        self._last_frame_time = now

        return BehaviorDecision(
            state=decision_state,
            cues=cues,
            should_classify=should_classify,
            suppression_active=self.suppression_active,
            last_emitted_at=self.last_emitted_at,
            candidate=self.candidate,
            person_boxes=person_dets,
            carryable_boxes=carryable_dets,
            near_miss=near_miss,
        )

    def _scene_is_clear(self, now: float, person_in_zone_now: bool, carryable_active: bool) -> bool:
        """Scene is cleared when no interaction signal for N seconds OR person
        has been out of zone long enough."""
        cand = self.candidate
        if cand is None:
            return True
        last_signal = max(cand.last_zone_seen_at, cand.last_carryable_seen_at)
        if last_signal <= 0:
            return False
        no_signal_for = now - last_signal
        if no_signal_for >= self.scene_clear_seconds:
            return True
        # Person-leaves-zone path
        if not person_in_zone_now and self.person_track is not None:
            since_in_zone = now - self.person_track.last_seen_in_zone_at
            if since_in_zone >= self.config.person_exit_seconds and not carryable_active:
                return True
        return False

    @staticmethod
    def _pair_distance_score(
        person_box: tuple[float, float, float, float],
        carryable_box: tuple[float, float, float, float] | None,
    ) -> tuple[float, float]:
        if carryable_box is None:
            return (float("inf"), float("inf"))
        iou = _box_iou(person_box, carryable_box)
        cx_p, cy_p = _box_center(person_box)
        cx_c, cy_c = _box_center(carryable_box)
        dist = ((cx_p - cx_c) ** 2 + (cy_p - cy_c) ** 2) ** 0.5
        return (dist, -iou)

    @staticmethod
    def _carryable_track_key(det: Detection) -> str:
        cx, cy = _box_center(det.box)
        return f"{det.label}:{int(cx // 80)}:{int(cy // 80)}"

    @staticmethod
    def _box_shift_pixels(
        anchor_box: tuple[float, float, float, float] | None,
        current_box: tuple[float, float, float, float],
    ) -> float:
        if anchor_box is None:
            return 0.0
        ax, ay = _box_center(anchor_box)
        cx, cy = _box_center(current_box)
        return ((ax - cx) ** 2 + (ay - cy) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Debug overlay rendering
# ---------------------------------------------------------------------------


_TIER_LABELS_OVERLAY = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}
_TIER_COLORS = {
    1: (160, 160, 160),  # gray
    2: (0, 220, 255),    # yellow
    3: (0, 140, 255),    # orange
    4: (0, 0, 255),      # red
}
_CARRYABLE_BOX_COLOR = (255, 80, 220)
_CARDBOARD_BOX_COLOR = (255, 0, 255)
# Bright cyan reserved for face-filter "known" person boxes — visually
# distinct from the default green so the operator instantly sees that the
# subject is enrolled and theft alerts are being suppressed for them.
_KNOWN_PERSON_BOX_COLOR = (255, 220, 0)


# Person threshold matches the confidence floor the theft tracker would
# act on, so the overlay shows what the system actually sees. 0.70 was
# too strict — when a subject fills the frame, YOLO scores them ~0.50-0.65
# because only a partial torso is visible, and they vanished from the box
# overlay even though they were being tracked.
_OVERLAY_MIN_CONFIDENCE = 0.50
# Cardboard floor balances "rendering real boxes" against "hallucinating
# on chair backs and table edges". YOLO-World false-positives at 0.10-0.20
# on any brown rectangular shape; legitimate cardboard typically clears
# 0.30. Matches the theft tracker's CARDBOARD_BOX_MIN_CONFIDENCE default.
_OVERLAY_MIN_CARDBOARD_CONFIDENCE = 0.30


def _draw_overlay(
    frame_bgr: Any,
    *,
    config: Config,
    decision: BehaviorDecision,
    last_classification: "LastClassification | None" = None,
) -> None:
    h, w = frame_bgr.shape[:2]
    candidate = decision.candidate
    cand_person_box = candidate.last_person_box if candidate else None
    cand_carryable_box = candidate.last_carryable_box if candidate else None

    def _draw(
        det: Detection,
        color: tuple[int, int, int],
        thickness: int,
        *,
        name_prefix: str | None = None,
    ) -> None:
        x1, y1, x2, y2 = (int(round(v)) for v in det.box)
        x1 = min(max(0, x1), max(0, w - 1))
        x2 = min(max(0, x2), max(0, w - 1))
        y1 = min(max(0, y1), max(0, h - 1))
        y2 = min(max(0, y2), max(0, h - 1))
        if x2 <= x1 or y2 <= y1:
            return
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, thickness)
        # Confidence chip in the top-left of the box. Filled rectangle with
        # the box's color, tight black text on top — black contrasts well
        # against the bright green / magenta / pink chip backgrounds. When
        # the face filter recognizes a person, prepend the matched name so
        # the operator can confirm at a glance that suppression is active.
        label = (
            f"{name_prefix} {det.confidence:.2f}"
            if name_prefix
            else f"{det.confidence:.2f}"
        )
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        chip_w = tw + 8
        chip_h = th + 6
        chip_x1 = max(0, min(x1, w - chip_w))
        chip_y2 = y1
        chip_y1 = y1 - chip_h
        if chip_y1 < 0:
            chip_y1 = y1
            chip_y2 = min(h - 1, y1 + chip_h)
            text_y = chip_y2 - 4
        else:
            text_y = chip_y2 - 4
        cv2.rectangle(frame_bgr, (chip_x1, chip_y1), (chip_x1 + chip_w, chip_y2), color, -1)
        cv2.putText(
            frame_bgr,
            label,
            (chip_x1 + 4, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    for idx, det in enumerate(decision.person_boxes):
        if det.confidence < _OVERLAY_MIN_CONFIDENCE:
            continue
        is_candidate = cand_person_box is not None and _box_iou(det.box, cand_person_box) > 0.3
        # Look up the matching face verdict (aligned 1:1 with person_boxes
        # when the face filter is enabled). Knowns get a brighter green +
        # name-prefixed chip so suppression is visually obvious during demo.
        verdict = (
            decision.face_verdicts[idx]
            if idx < len(decision.face_verdicts)
            else None
        )
        if verdict is not None and verdict.is_known:
            _draw(
                det,
                _KNOWN_PERSON_BOX_COLOR,
                3 if is_candidate else 2,
                name_prefix=verdict.name,
            )
        else:
            _draw(det, (0, 255, 0), 3 if is_candidate else 2)

    for det in decision.carryable_boxes:
        is_cardboard = det.label.strip().lower() == "cardboard box"
        min_conf = (
            _OVERLAY_MIN_CARDBOARD_CONFIDENCE
            if is_cardboard
            else _OVERLAY_MIN_CONFIDENCE
        )
        if det.confidence < min_conf:
            continue
        is_candidate = cand_carryable_box is not None and _box_iou(det.box, cand_carryable_box) > 0.3
        color = _CARDBOARD_BOX_COLOR if is_cardboard else _CARRYABLE_BOX_COLOR
        _draw(det, color, 3 if is_candidate else 2)

    # Persistent anchor draw — fixes the static-scene flicker the user noticed.
    # YOLO-World scores stationary cardboard wobbly (often dipping below the
    # 0.30 overlay threshold for several frames in a row), so a per-frame
    # draw makes the magenta box vanish until the user moves and the score
    # re-spikes. Once the theft tracker has *anchored* a box (= multiple
    # consistent detections over `anchor_seconds`), we trust it and keep
    # rendering the anchor regardless of what THIS frame's confidence was.
    # The anchor naturally clears when the box leaves the scene long enough,
    # so this won't pin a stale ghost.
    anchor_box = decision.package_anchor_box
    if anchor_box is not None:
        anchor_label = (decision.package_anchor_label or "cardboard box").strip().lower()
        is_cardboard_anchor = anchor_label == "cardboard box"
        anchor_color = (
            _CARDBOARD_BOX_COLOR if is_cardboard_anchor else _CARRYABLE_BOX_COLOR
        )
        # Skip if the per-frame loop above already drew a box at this spot.
        already_covered = False
        for det in decision.carryable_boxes:
            det_label = det.label.strip().lower()
            det_min_conf = (
                _OVERLAY_MIN_CARDBOARD_CONFIDENCE
                if det_label == "cardboard box"
                else _OVERLAY_MIN_CONFIDENCE
            )
            if det.confidence >= det_min_conf and _box_iou(det.box, anchor_box) > 0.3:
                already_covered = True
                break
        if not already_covered:
            ax1, ay1, ax2, ay2 = (int(round(v)) for v in anchor_box)
            ax1 = min(max(0, ax1), max(0, w - 1))
            ax2 = min(max(0, ax2), max(0, w - 1))
            ay1 = min(max(0, ay1), max(0, h - 1))
            ay2 = min(max(0, ay2), max(0, h - 1))
            if ax2 > ax1 and ay2 > ay1:
                cv2.rectangle(frame_bgr, (ax1, ay1), (ax2, ay2), anchor_color, 2)


def _draw_qwen_panel(frame_bgr: Any, cls: "LastClassification") -> None:
    """Render Qwen's latest description as a translucent panel at the bottom."""
    h, w = frame_bgr.shape[:2]
    panel_h = 110
    overlay = frame_bgr.copy()
    cv2.rectangle(overlay, (0, h - panel_h), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame_bgr, 0.45, 0, frame_bgr)

    age_s = max(0.0, time.time() - cls.timestamp)
    tier_label = _TIER_LABELS_OVERLAY.get(cls.tier, "?")
    tier_color = _TIER_COLORS.get(cls.tier, (200, 200, 200))

    header = (
        f"QWEN  T{cls.tier} {tier_label}  "
        f"conf {cls.confidence:.2f}  "
        f"pattern {cls.behavior_pattern or '-'}  "
        f"({age_s:.1f}s ago)"
    )
    _put_outlined(frame_bgr, header, (12, h - panel_h + 22), 0.55, tier_color)

    scene_text = f"scene : {cls.scene or '-'}"
    desc_text = f"desc  : {cls.suspect_description or '-'}"
    summary_text = f"behave: {cls.one_line_summary or '-'}"

    for i, line in enumerate((scene_text, desc_text, summary_text)):
        _put_outlined(
            frame_bgr,
            _truncate_for_overlay(line, max_chars=int(w / 8.5)),
            (12, h - panel_h + 50 + i * 22),
            0.5,
            (240, 240, 240),
        )


def _put_outlined(
    frame_bgr: Any, text: str, origin: tuple[int, int], scale: float, color: tuple[int, int, int]
) -> None:
    cv2.putText(frame_bgr, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(frame_bgr, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, 1, cv2.LINE_AA)


def _truncate_for_overlay(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "\u2026"


# ANSI helpers — milestone events render as styled banners in the terminal.
_PRETTY_RESET = "\033[0m"
_PRETTY_BOLD = "\033[1m"
_PRETTY_DIM = "\033[2m"
_PRETTY_RED = "\033[91m"
_PRETTY_GREEN = "\033[92m"
_PRETTY_YELLOW = "\033[93m"
_PRETTY_CYAN = "\033[96m"

_PRETTY_TIER = {
    1: (_PRETTY_DIM, "AMBIENT"),
    2: (_PRETTY_CYAN, "NOTICE"),
    3: (_PRETTY_YELLOW, "ALERT"),
    4: (_PRETTY_RED, "EMERGENCY"),
}

_PRETTY_BAR = "━" * 60


_READY_BANNER_LINES = (
    "██████╗  ███████╗  █████╗  ██████╗  ██╗   ██╗",
    "██╔══██╗ ██╔════╝ ██╔══██╗ ██╔══██╗ ╚██╗ ██╔╝",
    "██████╔╝ █████╗   ███████║ ██║  ██║  ╚████╔╝ ",
    "██╔══██╗ ██╔══╝   ██╔══██║ ██║  ██║   ╚██╔╝  ",
    "██║  ██║ ███████╗ ██║  ██║ ██████╔╝    ██║   ",
    "╚═╝  ╚═╝ ╚══════╝ ╚═╝  ╚═╝ ╚═════╝     ╚═╝   ",
)


def _print_ready_banner() -> None:
    """Big block-letter READY shown when warmup completes.

    Loud on purpose: this is the visual cue during a demo that everything
    is hot and the next frame will fire detection at steady-state latency.
    """
    print()
    for line in _READY_BANNER_LINES:
        print(f"{_PRETTY_GREEN}{_PRETTY_BOLD}{line}{_PRETTY_RESET}")
    print()


def _print_pretty_event(event: dict[str, Any]) -> None:
    tier = int(event.get("tier", 1))
    color, name = _PRETTY_TIER.get(tier, (_PRETTY_RESET, "UNKNOWN"))
    pattern = event.get("behavior_pattern") or "-"
    confidence = float(event.get("confidence") or 0.0)
    summary = event.get("one_line_summary") or "-"
    desc = event.get("suspect_description") or "-"
    scene = event.get("scene") or "-"
    print()
    print(f"{color}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")
    print(
        f"{color}{_PRETTY_BOLD}  ▶ QWEN  T{tier} {name}{_PRETTY_RESET}"
        f"  conf {confidence:.2f}  pattern {pattern}"
    )
    print(f"  {_PRETTY_DIM}scene{_PRETTY_RESET}  {scene}")
    print(f"  {_PRETTY_DIM}desc {_PRETTY_RESET}  {desc}")
    print(f"  {_PRETTY_DIM}what {_PRETTY_RESET}  {summary}")
    print(f"{color}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")


def _print_pretty_theft(state: str, package: str | None, cues: list[str]) -> None:
    pkg = package or "?"
    cue_str = ", ".join(cues) if cues else "-"
    print()
    print(f"{_PRETTY_RED}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")
    print(f"{_PRETTY_RED}{_PRETTY_BOLD}  ▶ THEFT CONFIRMED  package={pkg}{_PRETTY_RESET}")
    print(f"  {_PRETTY_DIM}cues{_PRETTY_RESET}   {cue_str}")
    print(f"{_PRETTY_RED}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")


def _print_pretty_call(to: str, sid: str) -> None:
    print(f"{_PRETTY_GREEN}{_PRETTY_BOLD}  ✓ CALL PLACED{_PRETTY_RESET}  to={to}  sid={sid}")


def _draw_box(frame_bgr: Any, det: Detection, *, color: tuple[int, int, int], thickness: int) -> None:
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in det.box)
    x1 = min(max(0, x1), max(0, w - 1))
    x2 = min(max(0, x2), max(0, w - 1))
    y1 = min(max(0, y1), max(0, h - 1))
    y2 = min(max(0, y2), max(0, h - 1))
    if x2 <= x1 or y2 <= y1:
        return
    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, thickness)
    label = f"{det.label} {det.confidence:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    label_w = min(tw + 6, w)
    label_x1 = min(max(0, x1), max(0, w - label_w))
    label_y2 = y1
    label_y1 = y1 - th - 6
    if label_y1 < 0:
        label_y1 = y1
        label_y2 = min(h - 1, y1 + th + 6)
        text_y = min(h - 4, y1 + th + 2)
    else:
        text_y = y1 - 4
    cv2.rectangle(frame_bgr, (label_x1, label_y1), (label_x1 + label_w, label_y2), color, -1)
    cv2.putText(frame_bgr, label, (label_x1 + 3, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)


def _empty_decision() -> BehaviorDecision:
    return BehaviorDecision(
        state=STATE_IDLE,
        cues=[],
        should_classify=False,
        suppression_active=False,
        last_emitted_at=0.0,
        candidate=None,
        person_boxes=[],
        carryable_boxes=[],
        package_anchor_label=None,
        package_anchor_box=None,
        near_miss=False,
    )


# ---------------------------------------------------------------------------
# Vision Engine
# ---------------------------------------------------------------------------


class VisionEngine:
    def __init__(self, config: Config, source: int | str, show_window: bool) -> None:
        self.config = config
        self.device = require_mps()
        self.source = source
        self.show_window = show_window
        self.frame_buffer: deque[BufferedFrame] = deque(maxlen=FRAME_BUFFER_MAXLEN)
        self.frame_seq = 0
        self.classification_queue: queue.Queue[ClassificationRequest | None] = queue.Queue(
            maxsize=1
        )
        self.publish_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=max(1, int(config.event_queue_size))
        )
        self.artifact_queue: queue.Queue[ArtifactRequest | None] = queue.Queue(
            maxsize=max(1, int(config.artifact_queue_size))
        )
        self.classification_in_flight = False
        self.state_lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None
        self.publisher_thread: threading.Thread | None = None
        self.artifact_thread: threading.Thread | None = None
        self.capture_thread: threading.Thread | None = None
        self.processing_thread: threading.Thread | None = None
        self.run_event = threading.Event()
        self.capture_lock = threading.Lock()
        self.latest_capture_frame: Any | None = None
        self.latest_capture_at: float = 0.0
        self.last_processed_capture_at: float = 0.0
        self.decision_lock = threading.Lock()
        self.latest_decision: BehaviorDecision = _empty_decision()
        self.behavior = BehaviorTracker(config)
        self.theft_tracker = PackageTheftTracker(config)
        self.face_filter: FaceFilter | None = self._init_face_filter(config)
        # Sticky identity anchors — see _IdentityAnchor docstring. Survives
        # face-detection dropouts (subject turns to grab the box, lighting
        # changes, motion blur) so suppression doesn't blink off mid-action.
        self._identity_anchors: list[_IdentityAnchor] = []
        self._prev_motion_gray: Any | None = None
        self._artifact_dir_ensured = False
        # Demo-mode flag driving carryable label set
        self._carryable_label_set: set[str] = {
            self._normalize_monitored_label(label) for label in config.carryable_labels
        }
        # Latest Qwen output, surfaced on the camera overlay so you can SEE
        # what the model is saying about you in real time.
        self.last_classification = LastClassification()
        # Last time we fired a Qwen classification — used by the demo fast-path.
        self._last_fire_at: float = 0.0
        # Sticky incident lifecycle so one continuous scene only emits once.
        self._active_incident_id: str | None = None
        self._active_incident_last_signal_at: float = 0.0
        self._active_incident_alert_sent: bool = False
        # Throttle for "why didn't this fire" debug log so we don't spam.
        self._last_fire_block_log_at: float = 0.0
        self._router_url_warned = False
        self.yolo_world = None
        self._cardboard_backend_active = self._normalize_cardboard_backend(
            config.cardboard_detector_backend
        )

        self.yolo = YOLO(config.yolo_model)
        self.yolo.to(self.device)
        self._monitored_class_ids = self._resolve_monitored_class_ids()
        self._init_cardboard_detector()

        self.processor = None
        self.qwen = None
        self.cloud_classifier = None
        self._classifier_backend = (config.classifier_backend or "qwen").lower()
        if not self.config.mock_classifier:
            if self._classifier_backend == "cloud":
                # Cloud backend: zero local weights to load. Build a thin
                # client object lazily — first .classify() call constructs
                # the SDK client, validates the API key, and raises a
                # clear error if either is missing.
                from .cloud_classifier import CloudHeavyClassifier

                self.cloud_classifier = CloudHeavyClassifier(
                    model=config.cloud_classifier_model,
                    max_tokens=config.cloud_classifier_max_tokens,
                    max_edge=config.cloud_classifier_max_edge,
                    jpeg_quality=config.cloud_classifier_jpeg_quality,
                    timeout_seconds=config.cloud_classifier_timeout_seconds,
                )
            else:
                self.processor = AutoProcessor.from_pretrained(
                    config.qwen_model,
                    min_pixels=config.qwen_min_pixels,
                    max_pixels=config.qwen_max_pixels,
                )
                self.qwen = Qwen2VLForConditionalGeneration.from_pretrained(
                    config.qwen_model,
                    torch_dtype=torch.float16,
                )
                self.qwen = self.qwen.to(self.device)
                self.qwen.eval()
            self.worker_thread = threading.Thread(
                target=self._classification_worker,
                name="vlm-classifier",
                daemon=True,
            )
            self.worker_thread.start()
        if self.config.post_events:
            self.publisher_thread = threading.Thread(
                target=self._publisher_worker,
                name="event-publisher",
                daemon=True,
            )
            self.publisher_thread.start()
        if self.config.save_failure_artifacts:
            self.artifact_thread = threading.Thread(
                target=self._artifact_worker,
                name="artifact-writer",
                daemon=True,
            )
            self.artifact_thread.start()
        # Surface which VLM backend booted — qwen2-vl-2b on-device vs cloud Anthropic
        # — so the operator can tell at a glance and so logs are self-describing.
        if self._classifier_backend == "cloud":
            classifier_label = f"cloud:{self.config.cloud_classifier_model}"
        else:
            classifier_label = f"qwen:{self.config.qwen_model}"

        # Demo-critical: pay the cold-start cost NOW (graph compile, MPS
        # warmup, processor caches, cloud TLS handshake) so the first real
        # frame after the banner detects in steady-state latency.
        warm_summary = self._prewarm()

        _print_ready_banner()
        print(f"{_PRETTY_GREEN}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")
        print(f"  {_PRETTY_DIM}device  {_PRETTY_RESET} {self.device}")
        print(f"  {_PRETTY_DIM}yolo    {_PRETTY_RESET} {self.config.yolo_model}")
        print(f"  {_PRETTY_DIM}vlm     {_PRETTY_RESET} {classifier_label}")
        print(f"  {_PRETTY_DIM}cardbrd {_PRETTY_RESET} {self._cardboard_backend_active}")
        print(f"  {_PRETTY_DIM}capture {_PRETTY_RESET} {self.config.capture_width}x{self.config.capture_height}")
        print(f"  {_PRETTY_DIM}router  {_PRETTY_RESET} {'on' if self.config.post_events else 'off'}")
        print(f"  {_PRETTY_DIM}warmup  {_PRETTY_RESET} {warm_summary}")
        print(f"{_PRETTY_GREEN}{_PRETTY_BOLD}{_PRETTY_BAR}{_PRETTY_RESET}")
        print()
        log.info(
            "Vision engine ready device=%s source=%r yolo=%s classifier=%s capture=%sx%s "
            "person_conf=%s carryable_conf=%s zone=%s demo_bias=%s mock=%s post=%s overlay=%s artifacts=%s",
            self.device,
            self.source,
            self.config.yolo_model,
            classifier_label,
            self.config.capture_width,
            self.config.capture_height,
            self.config.person_confidence,
            self.config.carryable_confidence,
            self.config.entry_zone,
            self.config.demo_mode_theft_bias,
            self.config.mock_classifier,
            self.config.post_events,
            self.config.debug_overlay,
            self.config.save_failure_artifacts,
        )

    def _maintain_identity_anchors(
        self,
        persons: list[Detection],
        verdicts: list[Any],
        now: float,
    ) -> list[Any]:
        """Apply sticky-by-position identity anchoring to per-box verdicts.

        Returns the verdicts list with face-hidden boxes filled in from
        confirmed anchors (IoU + recency match). Mutates self._identity_anchors
        in place: refresh on fresh known verdicts, expire on lack of overlap.

        See _IdentityAnchor class docstring for the user-facing rules.
        """
        from .face_filter import PersonVerdict

        if not persons:
            # Persons all left frame — let anchors age out and clear if needed.
            self._identity_anchors = [
                a for a in self._identity_anchors
                if (now - a.last_seen_at) <= _ANCHOR_EXPIRE_SECONDS
            ]
            return list(verdicts)

        if not verdicts:
            verdicts = [PersonVerdict(None, 0.0, "no_face") for _ in persons]

        # Step 1: refresh / create anchors from THIS frame's high-confidence
        # known verdicts. We require similarity >= _ANCHOR_HIGH_CONF to seed
        # an anchor, but lower-confidence known matches still benefit from
        # already-confirmed anchors via the inherit step below.
        for det, verdict in zip(persons, verdicts):
            if verdict is None or not verdict.is_known:
                continue
            if verdict.similarity < _ANCHOR_HIGH_CONF:
                continue
            existing = next(
                (
                    a
                    for a in self._identity_anchors
                    if a.name == verdict.name
                    and _box_iou(a.box, det.box) >= _ANCHOR_IOU
                ),
                None,
            )
            if existing is None:
                self._identity_anchors.append(
                    _IdentityAnchor(
                        name=verdict.name,
                        box=det.box,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_known_seen_at=now,
                    )
                )
                continue
            existing.box = det.box
            existing.last_seen_at = now
            existing.last_known_seen_at = now
            if (
                not existing.confirmed
                and (now - existing.first_seen_at) >= _ANCHOR_CONFIRM_SECONDS
            ):
                existing.confirmed = True
                log.info(
                    "Identity anchor CONFIRMED: %s (sustained %.2fs at sim>=%.2f)",
                    existing.name,
                    now - existing.first_seen_at,
                    _ANCHOR_HIGH_CONF,
                )

        # Step 2: for each person box that DOESN'T have a known verdict and
        # whose face wasn't visibly someone-else, inherit identity from a
        # confirmed anchor whose last verified sighting was recent.
        augmented: list[Any] = []
        for det, verdict in zip(persons, verdicts):
            if verdict is not None and verdict.is_known:
                augmented.append(verdict)
                continue
            # If the face was clearly seen but didn't match anyone, that's a
            # different person — never inherit. Otherwise (no_face,
            # face_too_small, low_quality, extreme_yaw) the face is hidden
            # and inheritance is safe.
            if verdict is not None and verdict.reason == "unknown":
                augmented.append(verdict)
                continue
            matched = next(
                (
                    a
                    for a in self._identity_anchors
                    if a.confirmed
                    and _box_iou(a.box, det.box) >= _ANCHOR_IOU
                    and (now - a.last_known_seen_at) <= _ANCHOR_INHERIT_WINDOW_SECONDS
                ),
                None,
            )
            if matched is not None:
                matched.last_seen_at = now
                matched.box = det.box  # smooth track to current YOLO box
                augmented.append(
                    PersonVerdict(matched.name, 0.99, "anchored")
                )
            else:
                augmented.append(
                    verdict if verdict is not None else PersonVerdict(None, 0.0, "no_face")
                )

        # Step 3: expire anchors that haven't been refreshed (= subject left).
        before = len(self._identity_anchors)
        self._identity_anchors = [
            a for a in self._identity_anchors
            if (now - a.last_seen_at) <= _ANCHOR_EXPIRE_SECONDS
        ]
        if len(self._identity_anchors) < before:
            log.info(
                "Identity anchor expired (subject left frame, no overlap for >%.1fs)",
                _ANCHOR_EXPIRE_SECONDS,
            )

        return augmented

    def _resolve_face_db_path(self, config: Config) -> str:
        """Return the gallery file we should actually load.

        Prefer the configured FACE_DB_PATH (typically the production
        family_faces/embeddings.json that scripts.face_setup writes). If
        that file is missing or empty, fall back to the committed demo
        gallery at face_demo/gallery.json — that's the file Aditya's
        face_id_demo.py enroll command appends to and pushes to git, so
        any checkout where the team has been demoing has it pre-populated.
        load_database() handles either schema.
        """
        configured = Path(config.face_db_path)
        if configured.exists() and configured.stat().st_size > 0:
            return str(configured)
        demo = Path("face_demo/gallery.json")
        if demo.exists() and demo.stat().st_size > 0:
            log.info(
                "FACE_DB_PATH=%s missing/empty; falling back to demo gallery %s",
                configured,
                demo,
            )
            return str(demo)
        return str(configured)

    def _init_face_filter(self, config: Config) -> "FaceFilter | None":
        """Build the family-face exclusion layer if FACE_FILTER_ENABLED=true.

        Fail-soft on every failure mode that isn't a flat misconfiguration:
        the alert path is more important than the suppression layer, so a
        missing DB / missing model / missing onnxruntime should log loudly
        and return None instead of crashing engine boot. The processing
        loop checks `self.face_filter is not None` before consulting it.
        """
        if not config.face_filter_enabled:
            return None
        from .face_filter import InsightFaceEmbedder
        db_path = self._resolve_face_db_path(config)
        try:
            embedder = InsightFaceEmbedder(
                model_name=config.face_model_name,
                apply_clahe=config.face_clahe_enabled,
            )
            face_filter = FaceFilter(
                db_path=db_path,
                similarity_threshold=config.face_similarity_threshold,
                min_face_pixels=config.face_min_pixels,
                min_det_score=config.face_min_det_score,
                max_yaw_degrees=config.face_max_yaw_degrees,
                max_pitch_degrees=config.face_max_pitch_degrees,
                topk_match=config.face_topk_match,
                embedder=embedder,
            )
        except Exception as exc:
            log.warning(
                "Face filter init failed (%s); proceeding with face_filter=None. "
                "Set FACE_FILTER_ENABLED=false to silence this warning.",
                exc,
            )
            return None
        names = face_filter.enrolled_names
        log.info(
            "Face filter enabled: db=%s enrolled=%d (%s) threshold=%.2f",
            db_path,
            len(names),
            ", ".join(names) if names else "—",
            config.face_similarity_threshold,
        )
        if not names:
            log.warning(
                "Face filter is enabled but the DB is empty — the engine will "
                "treat every person as unknown and never suppress. Verify "
                "FACE_DB_PATH or run scripts.face_setup / scripts/face_id_demo.py enroll.",
            )
        return face_filter

    @staticmethod
    def _normalize_cardboard_backend(raw: str) -> str:
        backend = (raw or "opencv").strip().lower().replace("-", "_")
        if backend in {"world", "yoloworld", "yolo_world"}:
            return "yolo_world"
        if backend in {"cv", "opencv", "color", "color_shape"}:
            return "opencv"
        if backend in {"auto", "off"}:
            return backend
        log.warning("Unknown CARDBOARD_DETECTOR_BACKEND=%r; using opencv", raw)
        return "opencv"

    def _init_cardboard_detector(self) -> None:
        if not self.config.cardboard_box_enable:
            self._cardboard_backend_active = "off"
            return
        if self._cardboard_backend_active not in {"yolo_world", "auto"}:
            return
        if YOLOWorld is None:
            log.warning("YOLO-World is unavailable in this Ultralytics install.")
            self._cardboard_backend_active = (
                "opencv" if self._cardboard_backend_active == "auto" else "off"
            )
            return

        classes = [label.strip() for label in self.config.yolo_world_cardboard_classes if label.strip()]
        if not classes:
            classes = ["cardboard box"]
        try:
            self.yolo_world = YOLOWorld(self.config.yolo_world_model)
            self.yolo_world.set_classes(classes)
            self.yolo_world.to(self.device)
            self._cardboard_backend_active = "yolo_world"
            log.info(
                "YOLO-World cardboard detector ready model=%s classes=%s",
                self.config.yolo_world_model,
                classes,
            )
        except Exception as exc:  # pragma: no cover - network/model availability varies
            log.warning("Could not initialize YOLO-World cardboard detector: %s", exc)
            self.yolo_world = None
            self._cardboard_backend_active = (
                "opencv" if self._cardboard_backend_active == "auto" else "off"
            )

    def _prewarm(self) -> str:
        """Run a dummy inference through every loaded model so the first real
        frame after startup hits steady-state latency.

        Demo-critical: without this the first YOLO call pays MPS graph
        compile (~1s), the first Qwen `generate()` pays caches + kernel
        compile (~2-3s), and the first cloud round-trip pays TLS handshake.
        We swallow the cost here so the camera-loop's first frame reports
        a normal ~50ms detection instead of stalling for several seconds.
        """
        import numpy as np

        t0 = time.time()
        statuses: list[str] = []

        dummy = np.zeros(
            (self.config.capture_height, self.config.capture_width, 3),
            dtype=np.uint8,
        )

        try:
            self.yolo.predict(
                source=dummy,
                classes=self._monitored_class_ids,
                conf=min(self.config.person_confidence, self.config.carryable_confidence),
                device=self.device,
                imgsz=self.config.yolo_input_size,
                verbose=False,
            )
            # Also warm the busy-state imgsz so dynamic switches don't recompile.
            busy = max(64, int(self.config.yolo_input_size_busy or 0))
            if busy and busy != self.config.yolo_input_size:
                self.yolo.predict(
                    source=dummy,
                    classes=self._monitored_class_ids,
                    conf=0.25,
                    device=self.device,
                    imgsz=busy,
                    verbose=False,
                )
            statuses.append("yolo")
        except Exception as exc:
            log.warning("YOLO prewarm failed: %s", exc)
            statuses.append("yolo:err")

        if self.yolo_world is not None:
            try:
                self.yolo_world.predict(
                    source=dummy,
                    conf=float(self.config.yolo_world_confidence),
                    device=self.device,
                    imgsz=max(64, int(self.config.yolo_world_input_size)),
                    verbose=False,
                )
                statuses.append("yolo-world")
            except Exception as exc:
                log.warning("YOLO-World prewarm failed: %s", exc)
                statuses.append("yolo-world:err")

        if not self.config.mock_classifier and (
            self.qwen is not None or self.cloud_classifier is not None
        ):
            try:
                self._classify_with_qwen([dummy], 0.0)
                statuses.append("vlm")
            except Exception as exc:
                log.warning("VLM prewarm failed: %s", exc)
                statuses.append("vlm:err")

        elapsed = time.time() - t0
        return f"{', '.join(statuses) or 'none'} ({elapsed:.1f}s)"

    # ---------------------------------------------------------------------
    # Capture loop
    # ---------------------------------------------------------------------

    def run(self) -> None:
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            raise RuntimeError(
                f"Unable to open camera source {self.source!r}. "
                "Check that the webcam or RTSP stream is accessible."
            )

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.capture_height)

        if self.show_window:
            print("Vision engine running. Press 'q' in the preview window to quit.")
        else:
            print("Vision engine running without a preview window. Use Ctrl+C to quit.")

        self.run_event.set()
        self.capture_thread = threading.Thread(
            target=self._capture_worker,
            args=(cap,),
            name="camera-capture",
            daemon=True,
        )
        self.capture_thread.start()

        # Demo-critical: block until the camera has produced at least one
        # real frame before starting the processing worker. Otherwise the
        # first ~100-500ms of "running" is just polling None frames while
        # the webcam negotiates, and a fast suspect can walk through
        # before frame 0 arrives.
        camera_warm_deadline = time.time() + 3.0
        while time.time() < camera_warm_deadline:
            with self.capture_lock:
                if self.latest_capture_frame is not None:
                    break
            time.sleep(0.02)

        self.processing_thread = threading.Thread(
            target=self._processing_worker,
            name="vision-processing",
            daemon=True,
        )
        self.processing_thread.start()

        try:
            while self.run_event.is_set():
                loop_started_at = time.time()
                frame, _ = self._get_latest_capture_frame()
                if frame is None:
                    self._throttle_display_loop(loop_started_at)
                    continue

                if self.show_window:
                    display = frame.copy()
                    if self.config.debug_overlay:
                        with self.decision_lock:
                            decision = self.latest_decision
                        with self.state_lock:
                            last_cls = self.last_classification
                        _draw_overlay(
                            display,
                            config=self.config,
                            decision=decision,
                            last_classification=last_cls,
                        )
                    cv2.imshow("ThirdEye Vision Engine", display)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        self.run_event.clear()
                        break

                self._throttle_display_loop(loop_started_at)
        finally:
            self.run_event.clear()
            if self.capture_thread is not None:
                self.capture_thread.join(timeout=1.0)
            if self.processing_thread is not None:
                self.processing_thread.join(timeout=1.0)
            cap.release()
            if self.show_window:
                cv2.destroyAllWindows()
            self._stop_worker()
            self._stop_background_workers()

    # ---------------------------------------------------------------------
    # Detection helpers
    # ---------------------------------------------------------------------

    def _capture_worker(self, cap: Any) -> None:
        while self.run_event.is_set():
            ok, frame = self._read_latest_frame(cap)
            if not ok:
                time.sleep(0.01)
                continue
            with self.capture_lock:
                self.latest_capture_frame = frame
                self.latest_capture_at = time.time()

    def _get_latest_capture_frame(self) -> tuple[Any | None, float]:
        with self.capture_lock:
            if self.latest_capture_frame is None:
                return None, 0.0
            return self.latest_capture_frame.copy(), self.latest_capture_at

    def _processing_worker(self) -> None:
        while self.run_event.is_set():
            loop_started_at = time.time()
            frame, captured_at = self._get_latest_capture_frame()
            if frame is None or captured_at <= self.last_processed_capture_at:
                self._throttle_loop(loop_started_at)
                continue
            if self.config.pause_detection_while_classifying and self._classification_busy():
                # Avoid YOLO+Qwen contention on MPS; capture/display continues
                # independently so the preview remains responsive.
                self._throttle_loop(loop_started_at)
                continue
            self.last_processed_capture_at = captured_at

            self.frame_seq += 1
            self.frame_buffer.append(
                BufferedFrame(timestamp=captured_at, frame_bgr=frame.copy())
            )

            _fh, _fw = frame.shape[:2]
            persons, carryables = self._detect_persons_and_carryables(frame)
            self._update_active_incident(
                now=captured_at,
                has_signal=bool(persons or carryables),
            )
            person_boxes = [d.box for d in persons]
            package_dets = [
                PackageDetection(label=d.label, confidence=d.confidence, box=d.box)
                for d in carryables
            ]
            feet_motion = self._detect_feet_motion_in_entry_zone(frame)
            theft_decision = self.theft_tracker.update(
                now=captured_at,
                person_boxes=person_boxes,
                package_dets=package_dets,
                feet_motion_present=feet_motion,
            )
            decision = self._behavior_from_theft(theft_decision, persons, carryables)

            if self.config.debug_detections:
                log.info(
                    "frame=%d state=%s cues=%s persons=%s carryables=%s",
                    self.frame_seq,
                    decision.state,
                    decision.cues,
                    [(d.label, round(d.confidence, 2)) for d in persons],
                    [(d.label, round(d.confidence, 2)) for d in carryables],
                )

            # Face filter runs EVERY frame with persons (not just when about
            # to fire) so the overlay can stamp `aditya 0.92` on the bounding
            # box continuously — that's the visual proof the suppression
            # logic is alive. We compute per-detection verdicts (aligned 1:1
            # with `persons`) and then apply sticky identity anchoring so a
            # subject who turns to grab the box doesn't briefly drop out of
            # recognition mid-action.
            face_verdicts: list[Any] = []
            if self.face_filter is not None and persons:
                try:
                    person_boxes = [d.box for d in persons]
                    face_verdicts = self.face_filter.verdict_per_box(frame, person_boxes)
                except Exception as exc:
                    log.warning("Face filter raised; per-box verdicts skipped: %s", exc)
                    face_verdicts = []
                face_verdicts = self._maintain_identity_anchors(
                    persons, face_verdicts, captured_at
                )
            elif self.face_filter is not None:
                # No persons in frame — let anchors age out so a stale Aditya
                # tag doesn't survive into the next person who walks up.
                self._maintain_identity_anchors([], [], captured_at)
            decision = BehaviorDecision(
                state=decision.state,
                cues=decision.cues,
                should_classify=decision.should_classify,
                suppression_active=decision.suppression_active,
                last_emitted_at=decision.last_emitted_at,
                candidate=decision.candidate,
                person_boxes=decision.person_boxes,
                carryable_boxes=decision.carryable_boxes,
                package_anchor_label=decision.package_anchor_label,
                package_anchor_box=decision.package_anchor_box,
                near_miss=decision.near_miss,
                face_verdicts=face_verdicts,
            )
            with self.decision_lock:
                self.latest_decision = decision

            should_fire = theft_decision.should_emit
            if should_fire and face_verdicts:
                # Suppress only when EVERY visible person matched a known
                # enrolled identity. Fail-open on no_face / face_too_small /
                # low_quality / extreme_yaw so a stranger at a bad angle
                # never gets silently whitelisted.
                known = [v for v in face_verdicts if v.is_known]
                if known and len(known) == len(face_verdicts):
                    names = sorted({v.name for v in known})
                    log.info(
                        "Face filter SUPPRESS: every visible person matched "
                        "enrolled identity (%s); skipping theft emit %s",
                        ", ".join(names),
                        self._active_incident_id,
                    )
                    should_fire = False
                else:
                    log.info(
                        "Face filter PASS (alert allowed): %s",
                        ", ".join(
                            f"{v.name or v.reason}({v.similarity:.2f})"
                            for v in face_verdicts
                        ),
                    )
            if should_fire and self._should_suppress_duplicate_theft_emit():
                log.info(
                    "Suppressing duplicate theft emit for active incident %s",
                    self._active_incident_id,
                )
                should_fire = False

            if not should_fire and persons:
                self._log_fire_block(
                    decision=decision,
                    persons=persons,
                    carryables=carryables,
                    now=captured_at,
                )

            if should_fire:
                yolo_classes = sorted(
                    {d.label for d in persons} | {d.label for d in carryables}
                ) or ["person"]
                _print_pretty_theft(
                    theft_decision.state,
                    theft_decision.anchor_label,
                    list(theft_decision.cues),
                )
                latest_frame = self.frame_buffer[-1]

                if self.config.mock_classifier:
                    parsed, raw = self._classify_with_qwen([frame], 0.0)
                    if parsed is None:
                        parsed = {
                            "tier": 3,
                            "behavior_pattern": "taking_item",
                            "confidence": 0.6,
                            "scene": "the camera view",
                            "suspect_description": "person near the package",
                            "one_line_summary": "Person removed a package from the monitored zone",
                            "time_elapsed": "0.00s",
                        }
                    else:
                        parsed = {
                            "tier": 3,
                            "behavior_pattern": "taking_item",
                            "confidence": float(parsed.get("confidence", 0.6)),
                            "scene": str(parsed.get("scene", "the camera view")),
                            "suspect_description": str(
                                parsed.get("suspect_description", "person near the package")
                            ),
                            "one_line_summary": str(
                                parsed.get(
                                    "one_line_summary",
                                    "Person removed a package from the monitored zone",
                                )
                            ),
                            "time_elapsed": str(parsed.get("time_elapsed", "0.00s")),
                        }
                    event = build_event(
                        classification=parsed,
                        node_id=self.config.node_id,
                        frame_seq=self.frame_seq,
                        yolo_classes=yolo_classes,
                        raw_classifier=raw,
                        incident_id=self._incident_id_for_emit(captured_at),
                    )
                    self._update_last_classification(event)
                    _print_pretty_event(event)
                    self._fire_theft_alert(event, frame)
                    fired = True
                    self._mark_incident_emitted(captured_at)
                    self._last_fire_at = captured_at
                else:
                    recent = self._collect_recent_frames(self.config.qwen_frames_per_inference)
                    request = ClassificationRequest(
                        timestamp=latest_frame.timestamp,
                        frame_seq=self.frame_seq,
                        frame_bgr=latest_frame.frame_bgr.copy(),
                        yolo_classes=yolo_classes,
                        extra_frames=recent[:-1],
                    )
                    fired = self._submit_classification(request)
                    if fired:
                        self._mark_incident_emitted(captured_at)
                        self._last_fire_at = captured_at

                if self.config.save_failure_artifacts:
                    self._save_artifact(
                        kind="emit" if fired else "emit_dropped",
                        frame_bgr=latest_frame.frame_bgr,
                        decision=decision,
                        persons=persons,
                        carryables=carryables,
                    )
            elif decision.near_miss and self.config.save_failure_artifacts:
                self._save_artifact(
                    kind="near_miss",
                    frame_bgr=frame,
                    decision=decision,
                    persons=persons,
                    carryables=carryables,
                )

            self._throttle_loop(loop_started_at)

    def _detected_classes(self, frame_bgr: Any) -> list[str]:
        """Legacy entry-point kept for tests + simple callers."""
        imgsz = self._active_yolo_input_size()
        results = self.yolo.predict(
            source=frame_bgr,
            classes=self._monitored_class_ids,
            conf=min(self.config.person_confidence, self.config.carryable_confidence),
            device=self.device,
            imgsz=imgsz,
            verbose=False,
        )
        if not results:
            return []

        names = results[0].names
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []

        detected_ids = {int(cls_id) for cls_id in boxes.cls.tolist()}
        return sorted(str(names[idx]) for idx in detected_ids)

    def _detect_persons_and_carryables(
        self, frame_bgr: Any
    ) -> tuple[list[Detection], list[Detection]]:
        """Run YOLO once at the lower threshold and post-filter per class."""
        persons: list[Detection] = []
        carryables: list[Detection] = []
        if hasattr(frame_bgr, "shape") and len(frame_bgr.shape) >= 2:
            frame_h, frame_w = frame_bgr.shape[:2]
        else:
            frame_h, frame_w = self.config.capture_height, self.config.capture_width
        frame_size = (frame_w, frame_h)
        frame_area = float(frame_w * frame_h)

        lower_conf = min(self.config.person_confidence, self.config.carryable_confidence)
        imgsz = self._active_yolo_input_size()
        results = self.yolo.predict(
            source=frame_bgr,
            classes=self._monitored_class_ids,
            conf=lower_conf,
            device=self.device,
            imgsz=imgsz,
            verbose=False,
        )
        if not results:
            return persons, self._append_cardboard_boxes(
                frame_bgr, frame_size=frame_size, persons=persons, carryables=carryables
            )

        result = results[0]
        names = result.names
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return persons, self._append_cardboard_boxes(
                frame_bgr, frame_size=frame_size, persons=persons, carryables=carryables
            )

        cls_list = boxes.cls.tolist()
        try:
            conf_list = boxes.conf.tolist()
            xyxy_list = boxes.xyxy.tolist()
        except AttributeError:
            return persons, self._append_cardboard_boxes(
                frame_bgr, frame_size=frame_size, persons=persons, carryables=carryables
            )

        for cls_id, conf, xyxy in zip(cls_list, conf_list, xyxy_list):
            cls_id = int(cls_id)
            label = str(names.get(cls_id, str(cls_id))) if hasattr(names, "get") else str(names[cls_id])
            box = (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]))
            det = Detection(cls_id=cls_id, label=label, confidence=float(conf), box=box)
            if cls_id == PERSON_CLASS_ID:
                if self._allow_person_detection(det, frame_size=frame_size, frame_area=frame_area):
                    persons.append(det)
            elif self._normalize_monitored_label(label) in self._carryable_label_set:
                if self._allow_carryable_detection(det, frame_bgr=frame_bgr, frame_size=frame_size):
                    carryables.append(det)
        carryables = self._append_cardboard_boxes(
            frame_bgr, frame_size=frame_size, persons=persons, carryables=carryables
        )
        return persons, carryables

    def _active_yolo_input_size(self) -> int:
        """Pick YOLO inference size based on current engine load.

        Qwen and YOLO both run on MPS in this project. When Qwen generation is
        in-flight, shrinking YOLO imgsz helps preserve preview smoothness.
        """
        base = max(64, int(self.config.yolo_input_size))
        busy = int(self.config.yolo_input_size_busy)
        if busy <= 0:
            return base
        if self._classification_busy():
            return max(64, min(base, busy))
        return base

    def _read_latest_frame(self, cap: Any) -> tuple[bool, Any]:
        """Read the freshest camera frame, dropping stale buffered frames.

        On some OpenCV backends (especially network/MJPEG streams), CAP_PROP_BUFFERSIZE
        is ignored and `read()` can lag behind real time under load. Grabbing a
        couple of queued frames before decoding keeps UI latency lower.
        """
        drain_count = max(0, int(self.config.capture_buffer_drain_grabs))
        if drain_count <= 0:
            return cap.read()

        grabbed = 0
        for _ in range(drain_count):
            if not cap.grab():
                break
            grabbed += 1
        if grabbed > 0:
            ok, frame = cap.retrieve()
            if ok:
                return ok, frame
        return cap.read()

    def _behavior_from_theft(
        self,
        theft_decision: TheftDecision,
        persons: list[Detection],
        carryables: list[Detection],
    ) -> BehaviorDecision:
        return BehaviorDecision(
            state=theft_decision.state,
            cues=list(theft_decision.cues),
            should_classify=theft_decision.should_emit,
            suppression_active=False,
            last_emitted_at=self.theft_tracker.last_emit_at,
            candidate=None,
            person_boxes=persons,
            carryable_boxes=carryables,
            package_anchor_label=theft_decision.anchor_label,
            package_anchor_box=theft_decision.anchor_box,
            near_miss=False,
        )

    def _detect_feet_motion_in_entry_zone(self, frame_bgr: Any) -> bool:
        if not self.config.feet_motion_enable:
            return False
        if not hasattr(frame_bgr, "shape") or len(frame_bgr.shape) < 2:
            return False

        h, w = frame_bgr.shape[:2]
        if self.config.use_entry_zone:
            x1 = int(self.config.entry_zone[0] * w)
            y1 = int(self.config.entry_zone[1] * h)
            x2 = int(self.config.entry_zone[2] * w)
            y2 = int(self.config.entry_zone[3] * h)
        else:
            x1, y1, x2, y2 = (0, 0, w, h)
        y_start = max(y1, int(h * 0.55))
        if x2 <= x1 or y2 <= y_start:
            return False

        roi = frame_bgr[y_start:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if self._prev_motion_gray is None:
            self._prev_motion_gray = gray
            return False

        diff = cv2.absdiff(self._prev_motion_gray, gray)
        self._prev_motion_gray = gray
        _, mask = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        total_area = 0.0
        for c in contours:
            total_area += cv2.contourArea(c)
        return total_area >= float(self.config.feet_motion_min_area)

    def _allow_person_detection(
        self,
        det: Detection,
        *,
        frame_size: tuple[int, int],
        frame_area: float,
    ) -> bool:
        if det.confidence < self.config.person_confidence:
            return False
        in_zone = (
            _point_in_zone(_box_center(det.box), self.config.entry_zone, frame_size)
            if self.config.use_entry_zone
            else True
        )
        if in_zone:
            return True
        area_ratio = _box_area(det.box) / max(frame_area, 1.0)
        if area_ratio < self.config.person_min_area_ratio:
            return False
        if _touches_frame_edge(det.box, frame_size, self.config.edge_margin_ratio):
            return False
        return True

    def _allow_carryable_detection(
        self,
        det: Detection,
        *,
        frame_bgr: Any,
        frame_size: tuple[int, int],
    ) -> bool:
        _ = frame_bgr
        normalized = self._normalize_monitored_label(det.label)
        min_conf = max(
            self.config.carryable_confidence,
            STRICT_OBJECT_CONFIDENCE.get(normalized, self.config.carryable_confidence),
        )
        if det.confidence < min_conf:
            return False
        if self.config.use_entry_zone and not _point_in_zone(
            _box_center(det.box), self.config.entry_zone, frame_size
        ):
            return False
        if _touches_frame_edge(det.box, frame_size, self.config.edge_margin_ratio):
            return False
        return True

    def _append_cardboard_boxes(
        self,
        frame_bgr: Any,
        *,
        frame_size: tuple[int, int],
        persons: list[Detection],
        carryables: list[Detection],
    ) -> list[Detection]:
        cardboard = self._detect_cardboard_boxes(
            frame_bgr,
            frame_size=frame_size,
            persons=persons,
        )
        if not cardboard:
            return carryables
        merged = list(carryables)
        for det in cardboard:
            if any(_box_iou(det.box, existing.box) > 0.35 for existing in merged):
                continue
            merged.append(det)
        return merged

    def _detect_cardboard_boxes(
        self,
        frame_bgr: Any,
        *,
        frame_size: tuple[int, int],
        persons: list[Detection] | None = None,
    ) -> list[Detection]:
        if not self.config.cardboard_box_enable:
            return []
        if not hasattr(frame_bgr, "shape") or len(frame_bgr.shape) < 2:
            return []
        if self._cardboard_backend_active == "yolo_world":
            return self._detect_cardboard_boxes_yolo_world(
                frame_bgr,
                frame_size=frame_size,
                persons=persons,
            )
        if self._cardboard_backend_active == "off":
            return []
        return self._detect_cardboard_boxes_opencv(
            frame_bgr,
            frame_size=frame_size,
            persons=persons,
        )

    def _detect_cardboard_boxes_yolo_world(
        self,
        frame_bgr: Any,
        *,
        frame_size: tuple[int, int],
        persons: list[Detection] | None = None,
    ) -> list[Detection]:
        if self.yolo_world is None:
            return []
        try:
            results = self.yolo_world.predict(
                source=frame_bgr,
                conf=float(self.config.yolo_world_confidence),
                device=self.device,
                imgsz=max(64, int(self.config.yolo_world_input_size)),
                verbose=False,
            )
        except Exception as exc:
            log.warning("YOLO-World cardboard inference failed: %s", exc)
            return []
        if not results:
            return []
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []
        try:
            conf_list = boxes.conf.tolist()
            xyxy_list = boxes.xyxy.tolist()
        except AttributeError:
            return []

        candidates: list[Detection] = []
        for conf, xyxy in zip(conf_list, xyxy_list):
            box = (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]))
            det = Detection(
                cls_id=-200,
                label="cardboard box",
                confidence=float(conf),
                box=box,
            )
            if self._allow_yolo_world_cardboard_detection(
                det,
                frame_size=frame_size,
                persons=persons or [],
            ):
                candidates.append(det)

        candidates.sort(key=lambda det: det.confidence, reverse=True)
        return candidates[:1]

    def _allow_yolo_world_cardboard_detection(
        self,
        det: Detection,
        *,
        frame_size: tuple[int, int],
        persons: list[Detection],
    ) -> bool:
        if det.confidence < float(self.config.yolo_world_confidence):
            return False
        if self.config.use_entry_zone and not _point_in_zone(
            _box_center(det.box), self.config.entry_zone, frame_size
        ):
            return False
        frame_w, frame_h = frame_size
        area_ratio = _box_area(det.box) / max(float(frame_w * frame_h), 1.0)
        if area_ratio < float(self.config.cardboard_box_min_area_ratio):
            return False
        max_area_ratio = max(float(self.config.cardboard_box_max_area_ratio), 0.55)
        if area_ratio > max_area_ratio:
            return False
        # Reject only when the cardboard box is essentially identical to a
        # person box (>=0.95 overlap) — that's almost certainly the model
        # tagging a torso shape as "cardboard". Lower thresholds rejected
        # legitimate detections of someone holding a box in front of them,
        # which is the canonical demo scene.
        if self._person_overlap_ratio(det.box, persons) > 0.95:
            return False
        x1, y1, x2, y2 = det.box
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        if width < 12.0 or height < 12.0:
            return False
        aspect = width / max(height, 1.0)
        return 0.20 <= aspect <= 5.0

    def _detect_cardboard_boxes_opencv(
        self,
        frame_bgr: Any,
        *,
        frame_size: tuple[int, int],
        persons: list[Detection] | None = None,
    ) -> list[Detection]:
        frame_w, frame_h = frame_size
        frame_area = max(1.0, float(frame_w * frame_h))
        min_area = frame_area * float(self.config.cardboard_box_min_area_ratio)
        max_area = frame_area * float(self.config.cardboard_box_max_area_ratio)

        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        # Cardboard under phone-camera lighting is usually yellow/tan. Keep
        # the hue away from red/pink because skin and hoodie sleeves otherwise
        # create large false boxes in the foreground.
        tan_mask = cv2.inRange(hsv, (14, 12, 35), (42, 220, 255))
        brown_mask = cv2.inRange(hsv, (12, 35, 30), (32, 255, 225))
        mask = cv2.bitwise_or(tan_mask, brown_mask)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, Detection]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area or area > max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            box = (float(x), float(y), float(x + w), float(y + h))
            if self.config.use_entry_zone and not _point_in_zone(
                _box_center(box), self.config.entry_zone, frame_size
            ):
                continue
            area_ratio = area / frame_area
            person_overlap = self._person_overlap_ratio(box, persons or [])
            touches_edge = _touches_frame_edge(
                box,
                frame_size,
                float(self.config.cardboard_box_edge_margin_ratio),
            )
            if touches_edge and area < max(min_area * 3.0, frame_area * 0.02):
                continue

            aspect = w / max(float(h), 1.0)
            if aspect < 0.35 or aspect > 3.0:
                continue
            extent = area / max(float(w * h), 1.0)
            if extent < float(self.config.cardboard_box_min_extent):
                continue

            mask_area = float(cv2.countNonZero(mask[y : y + h, x : x + w]))
            mask_coverage = mask_area / max(float(w * h), 1.0)
            score = self._cardboard_candidate_score(
                box,
                frame_size=frame_size,
                area_ratio=area_ratio,
                extent=extent,
                mask_coverage=mask_coverage,
                person_overlap=person_overlap,
            )
            if score < float(self.config.cardboard_box_min_score):
                continue

            confidence = min(0.88, max(float(self.config.cardboard_box_min_confidence), score))
            candidates.append(
                (
                    score,
                    Detection(
                        cls_id=-100,
                        label="cardboard box",
                        confidence=confidence,
                        box=box,
                    ),
                )
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        if candidates:
            return [candidates[0][1]]
        return []

    def _cardboard_candidate_score(
        self,
        box: tuple[float, float, float, float],
        *,
        frame_size: tuple[int, int],
        area_ratio: float,
        extent: float,
        mask_coverage: float,
        person_overlap: float,
    ) -> float:
        _frame_w, frame_h = frame_size
        _cx, cy = _box_center(box)
        cy_norm = cy / max(float(frame_h), 1.0)
        floor_min = float(self.config.cardboard_box_floor_min_y_ratio)
        floor_score = max(0.0, min(1.0, (cy_norm - (floor_min - 0.16)) / 0.28))
        size_score = max(0.0, min(1.0, area_ratio / 0.035))
        shape_score = max(0.0, min(1.0, extent / 0.70))
        color_score = max(0.0, min(1.0, mask_coverage / 0.65))
        person_penalty = max(0.0, min(0.80, person_overlap * 1.4))
        return (
            (0.34 * floor_score)
            + (0.24 * size_score)
            + (0.22 * shape_score)
            + (0.20 * color_score)
            - person_penalty
        )

    @staticmethod
    def _person_overlap_ratio(
        box: tuple[float, float, float, float],
        persons: list[Detection],
    ) -> float:
        if not persons:
            return 0.0
        bx1, by1, bx2, by2 = box
        box_area = max(1.0, _box_area(box))
        max_overlap = 0.0
        for person in persons:
            px1, py1, px2, py2 = person.box
            ix1 = max(bx1, px1)
            iy1 = max(by1, py1)
            ix2 = min(bx2, px2)
            iy2 = min(by2, py2)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            max_overlap = max(max_overlap, inter / box_area)
        return max_overlap

    def _resolve_monitored_class_ids(self) -> list[int]:
        names = getattr(self.yolo, "names", None)
        if names is None:
            names = getattr(getattr(self.yolo, "model", None), "names", None)
        if isinstance(names, list):
            name_map = {idx: str(label) for idx, label in enumerate(names)}
        elif isinstance(names, dict):
            name_map = {int(idx): str(label) for idx, label in names.items()}
        else:
            log.warning("Could not resolve YOLO class names; falling back to legacy carryable ids.")
            return [PERSON_CLASS_ID, *BOX_CLASS_IDS]

        inverse = {self._normalize_monitored_label(label): idx for idx, label in name_map.items()}
        class_ids = {PERSON_CLASS_ID}
        missing: list[str] = []
        for label in self._carryable_label_set:
            idx = inverse.get(label)
            if idx is None:
                missing.append(label)
                continue
            class_ids.add(idx)
        if missing:
            log.warning("Configured removable labels missing from YOLO model: %s", ", ".join(sorted(missing)))
        return sorted(class_ids)

    @staticmethod
    def _normalize_monitored_label(label: str) -> str:
        cleaned = str(label).strip().lower()
        return LABEL_ALIASES.get(cleaned, cleaned)

    # ---------------------------------------------------------------------
    # Classifier worker
    # ---------------------------------------------------------------------

    def _classify_with_qwen(
        self, frames_bgr: Any, time_elapsed_seconds: float
    ) -> tuple[dict[str, Any] | None, str]:
        # Accept either a single frame or a list — multi-frame is the new path
        # but the mock classifier still calls with a list of one.
        if not isinstance(frames_bgr, list):
            frames_bgr = [frames_bgr]
        if self.config.mock_classifier:
            raw_answer = json.dumps(
                {
                    "tier": 3,
                    "behavior_pattern": "taking_item",
                    "confidence": 0.80,
                    "scene": "the mock test scene",
                    "suspect_description": "MOCK MODE test person of unspecified appearance",
                    "one_line_summary": "MOCK MODE: vision pipeline is in mock mode and not using Qwen",
                    "time_elapsed": "ignored",
                }
            )
            result = evaluate_classifier_output(raw_answer, time_elapsed_seconds)
            return result.payload, raw_answer

        # Cloud backend: ship the most recent N frames to Claude. The
        # rule-based theft tracker has already gated us here, so paying a
        # cloud round-trip for the actual classification is fine — and
        # frees teammates on weak laptops from hosting Qwen weights.
        if self._classifier_backend == "cloud" and self.cloud_classifier is not None:
            try:
                raw_answer = self.cloud_classifier.classify(
                    list(frames_bgr), VISION_LANGUAGE_PROMPT,
                ).strip()
            except Exception as exc:
                log.warning("cloud classifier call failed: %s", exc)
                return None, ""
            result = evaluate_classifier_output(raw_answer, time_elapsed_seconds)
            if not result.ok:
                log.warning(
                    "cloud classifier output rejected [%s]: %s | raw=%r",
                    result.status,
                    result.reason,
                    raw_answer,
                )
            elif result.status == "degrade":
                log.info("cloud classifier output degraded to tier 1: %s", result.reason)
            return result.payload, raw_answer

        # Multi-frame: downscale each, build a multi-image content block.
        images = [frame_to_pil(self._downscale_frame_for_qwen(f)) for f in frames_bgr]
        content: list[dict[str, Any]] = [{"type": "image"} for _ in images]
        content.append({"type": "text", "text": VISION_LANGUAGE_PROMPT})
        messages = [{"role": "user", "content": content}]
        prompt_text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.processor(
            text=[prompt_text],
            images=images,
            padding=True,
            return_tensors="pt",
        )
        inputs = self._move_inputs_to_device(inputs)

        with torch.inference_mode():
            generated_ids = self.qwen.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=self.config.qwen_max_new_tokens,
            )

        prompt_length = inputs["input_ids"].shape[1]
        generated_ids = generated_ids[:, prompt_length:]
        raw_answer = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        self._empty_mps_cache()
        result = evaluate_classifier_output(raw_answer, time_elapsed_seconds)
        if not result.ok:
            log.warning(
                "Qwen output rejected [%s]: %s | raw=%r",
                result.status,
                result.reason,
                raw_answer,
            )
        elif result.status == "degrade":
            log.info("Qwen output degraded to tier 1: %s", result.reason)
        return result.payload, raw_answer

    def _submit_classification(self, request: ClassificationRequest) -> bool:
        if self.config.mock_classifier:
            return False
        with self.state_lock:
            if self.classification_in_flight:
                return False
            self.classification_in_flight = True
        try:
            self.classification_queue.put_nowait(request)
            return True
        except queue.Full:
            with self.state_lock:
                self.classification_in_flight = False
            return False

    def _classification_worker(self) -> None:
        while True:
            request = self.classification_queue.get()
            if request is None:
                self.classification_queue.task_done()
                return

            try:
                classification_started_at = time.time()
                # Pass the historical context frames first, then the most recent
                # frame last so Qwen knows which one is "now".
                frames = list(request.extra_frames) + [request.frame_bgr]
                parsed, raw_answer = self._classify_with_qwen(
                    frames,
                    classification_started_at - request.timestamp,
                )
                if parsed is None:
                    parsed = {
                        "tier": 3,
                        "behavior_pattern": "taking_item",
                        "confidence": 0.6,
                        "scene": "the camera view",
                        "suspect_description": "person near the package",
                        "one_line_summary": "Person removed a package from the monitored zone",
                        "time_elapsed": f"{classification_started_at - request.timestamp:.2f}s",
                    }
                else:
                    # Theft decision is YOLO+temporal only. Qwen enriches text,
                    # but must never downgrade/escalate the theft tier.
                    parsed = {
                        "tier": 3,
                        "behavior_pattern": "taking_item",
                        "confidence": float(parsed.get("confidence", 0.6)),
                        "scene": str(parsed.get("scene", "the camera view")),
                        "suspect_description": str(
                            parsed.get("suspect_description", "person near the package")
                        ),
                        "one_line_summary": str(
                            parsed.get(
                                "one_line_summary",
                                "Person removed a package from the monitored zone",
                            )
                        ),
                        "time_elapsed": str(
                            parsed.get(
                                "time_elapsed",
                                f"{classification_started_at - request.timestamp:.2f}s",
                            )
                        ),
                    }

                event = build_event(
                    classification=parsed,
                    node_id=self.config.node_id,
                    frame_seq=request.frame_seq,
                    yolo_classes=request.yolo_classes,
                    raw_classifier=raw_answer,
                    timestamp=request.timestamp,
                    incident_id=self._incident_id_for_emit(request.timestamp),
                )
                self._update_last_classification(event)
                _print_pretty_event(event)
                self._fire_theft_alert(event, request.frame_bgr)
            except Exception:
                log.exception("Background Qwen classification failed.")
            finally:
                with self.state_lock:
                    self.classification_in_flight = False
                self.classification_queue.task_done()

    def _stop_worker(self) -> None:
        if self.worker_thread is None:
            return
        try:
            self.classification_queue.put_nowait(None)
        except queue.Full:
            pass
        self.worker_thread.join(timeout=1.0)

    def _stop_background_workers(self) -> None:
        self._stop_queue_worker(self.publisher_thread, self.publish_queue)
        self._stop_queue_worker(self.artifact_thread, self.artifact_queue)

    @staticmethod
    def _stop_queue_worker(
        worker: threading.Thread | None,
        worker_queue: queue.Queue[Any],
    ) -> None:
        if worker is None:
            return
        try:
            worker_queue.put_nowait(None)
        except queue.Full:
            try:
                worker_queue.get_nowait()
                worker_queue.task_done()
                worker_queue.put_nowait(None)
            except Exception:
                pass
        worker.join(timeout=1.0)

    def _classification_busy(self) -> bool:
        with self.state_lock:
            return self.classification_in_flight

    def _publisher_worker(self) -> None:
        while True:
            event = self.publish_queue.get()
            try:
                if event is None:
                    return
                self._publish_event_sync(event)
            finally:
                self.publish_queue.task_done()

    def _artifact_worker(self) -> None:
        while True:
            request = self.artifact_queue.get()
            try:
                if request is None:
                    return
                self._save_artifact_sync(request)
            finally:
                self.artifact_queue.task_done()

    # ---------------------------------------------------------------------
    # Failure artifacts
    # ---------------------------------------------------------------------

    def _ensure_artifact_dir(self) -> str:
        path = self.config.debug_artifact_dir
        if not self._artifact_dir_ensured:
            os.makedirs(path, exist_ok=True)
            self._artifact_dir_ensured = True
        return path

    def _save_artifact(
        self,
        *,
        kind: str,
        frame_bgr: Any,
        decision: BehaviorDecision,
        persons: list[Detection],
        carryables: list[Detection],
    ) -> None:
        if not self.config.save_failure_artifacts:
            return
        frame_copy = frame_bgr.copy() if hasattr(frame_bgr, "copy") else frame_bgr
        request = ArtifactRequest(
            kind=kind,
            timestamp=time.time(),
            frame_seq=self.frame_seq,
            frame_bgr=frame_copy,
            decision=decision,
            persons=list(persons),
            carryables=list(carryables),
        )
        if self.artifact_thread is None:
            self._save_artifact_sync(request)
            return
        try:
            self.artifact_queue.put_nowait(request)
        except queue.Full:
            log.warning("Dropping %s artifact because artifact writer is behind.", kind)

    def _save_artifact_sync(self, request: ArtifactRequest) -> None:
        try:
            dir_path = self._ensure_artifact_dir()
            ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(request.timestamp))
            stem = f"{ts}_{request.kind}_{uuid.uuid4().hex[:6]}"
            jpg_path = os.path.join(dir_path, stem + ".jpg")
            meta_path = os.path.join(dir_path, stem + ".json")
            cv2.imwrite(jpg_path, request.frame_bgr)
            cand = request.decision.candidate
            meta = {
                "kind": request.kind,
                "timestamp": request.timestamp,
                "frame_seq": request.frame_seq,
                "state": request.decision.state,
                "cues": request.decision.cues,
                "suppression_active": request.decision.suppression_active,
                "persons": [
                    {"conf": p.confidence, "box": list(p.box)} for p in request.persons
                ],
                "carryables": [
                    {"label": c.label, "conf": c.confidence, "box": list(c.box)}
                    for c in request.carryables
                ],
                "candidate": None
                if cand is None
                else {
                    "first_seen_at": cand.first_seen_at,
                    "last_seen_at": cand.last_seen_at,
                    "interaction_frames": cand.interaction_frames,
                    "recent_zone_dwell": cand.recent_zone_dwell,
                    "last_carryable_label": cand.last_carryable_label,
                    "alert_fired": cand.alert_fired,
                },
            }
            with open(meta_path, "w") as fh:
                json.dump(meta, fh, indent=2)
        except Exception:
            log.exception("Failed to save failure artifact (kind=%s)", request.kind)

    # ---------------------------------------------------------------------
    # Misc
    # ---------------------------------------------------------------------

    def _downscale_frame_for_qwen(self, frame_bgr: Any) -> Any:
        max_edge = self.config.qwen_frame_max_edge
        height, width = frame_bgr.shape[:2]
        largest_edge = max(height, width)
        if largest_edge <= max_edge:
            return frame_bgr

        scale = max_edge / float(largest_edge)
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        return cv2.resize(frame_bgr, (new_width, new_height), interpolation=cv2.INTER_AREA)

    def _move_inputs_to_device(self, inputs: Any) -> dict[str, Any]:
        moved: dict[str, Any] = {}
        for key, value in inputs.items():
            moved[key] = value.to(self.device) if isinstance(value, torch.Tensor) else value
        return moved

    @staticmethod
    def _empty_mps_cache() -> None:
        mps = getattr(torch, "mps", None)
        if mps is None or not hasattr(mps, "empty_cache"):
            return
        try:
            mps.empty_cache()
        except RuntimeError:
            pass

    def _should_fast_path(
        self,
        persons: list[Detection],
        carryables: list[Detection],
        now: float,
    ) -> bool:
        """Demo fast-path: classify when behavior tracker hasn't fired in a while.

        Real production deployments rely on the BehaviorTracker zone+dwell+pair
        logic to suppress passersby. For a live demo we want classification to
        trigger reliably on a person within a few seconds even if the entry
        zone or pairing thresholds aren't perfectly tuned. This kicks in only
        when no fire has happened recently.
        """
        if not self.config.demo_fast_path:
            return False
        if not persons:
            return False
        if self._active_incident_alert_sent or self.behavior.suppression_active:
            return False
        if self._classification_busy():
            return False
        if (now - self._last_fire_at) < self.config.demo_fast_path_cooldown_seconds:
            return False
        return True

    def _should_suppress_duplicate_theft_emit(self) -> bool:
        return self._active_incident_alert_sent

    def _incident_id_for_emit(self, now: float) -> str:
        if self._active_incident_id is None:
            self._active_incident_id = f"inc_{uuid.uuid4().hex[:12]}"
        self._active_incident_last_signal_at = max(self._active_incident_last_signal_at, now)
        return self._active_incident_id

    def _mark_incident_emitted(self, now: float) -> None:
        self._incident_id_for_emit(now)
        self._active_incident_alert_sent = True

    def _update_active_incident(self, *, now: float, has_signal: bool) -> None:
        if has_signal:
            self._active_incident_last_signal_at = now
            return
        if self._active_incident_id is None and not self._active_incident_alert_sent:
            return
        if self._active_incident_last_signal_at <= 0:
            return
        if (now - self._active_incident_last_signal_at) < self.behavior.scene_clear_seconds:
            return
        self._active_incident_id = None
        self._active_incident_last_signal_at = 0.0
        self._active_incident_alert_sent = False

    def _collect_recent_frames(self, count: int) -> list[Any]:
        """Sample up to `count` frames from the rolling buffer (oldest first).

        Used to give Qwen multi-frame context. We sample evenly across the
        most recent lookback window so motion (a punch, a grab) is visible
        without feeding Qwen stale frames from seconds ago.
        """
        if count <= 1 or len(self.frame_buffer) <= 1:
            return [self.frame_buffer[-1].frame_bgr.copy()] if self.frame_buffer else []
        latest_ts = self.frame_buffer[-1].timestamp
        min_ts = latest_ts - max(0.0, self.config.qwen_frame_lookback_seconds)
        buffered = [b for b in self.frame_buffer if b.timestamp >= min_ts]
        if not buffered:
            buffered = [self.frame_buffer[-1]]
        if len(buffered) <= count:
            return [b.frame_bgr.copy() for b in buffered]
        # Evenly spaced indices, always including the most recent.
        step = (len(buffered) - 1) / (count - 1)
        indices = sorted({int(round(i * step)) for i in range(count)})
        return [buffered[i].frame_bgr.copy() for i in indices]

    def _log_fire_block(
        self,
        *,
        decision: BehaviorDecision,
        persons: list[Detection],
        carryables: list[Detection],
        now: float,
    ) -> None:
        """Throttled log explaining why a frame with a person didn't classify."""
        if (now - self._last_fire_block_log_at) < 10.0:
            return
        self._last_fire_block_log_at = now
        reasons = []
        if not carryables:
            reasons.append("no carryable detected")
        if decision.candidate is None:
            reasons.append("no candidate (person + carryable not paired in zone)")
        elif any(c.startswith("carryable_removed:") for c in decision.cues):
            reasons.append("stationary object removal detected")
        elif decision.candidate.interaction_frames < self.behavior.interaction_frames_required:
            reasons.append(
                f"need {self.behavior.interaction_frames_required} paired frames, "
                f"have {decision.candidate.interaction_frames}"
            )
        elif decision.candidate.recent_zone_dwell < self.behavior.min_dwell_seconds:
            reasons.append(
                f"need {self.behavior.min_dwell_seconds:.2f}s dwell in zone, "
                f"have {decision.candidate.recent_zone_dwell:.2f}s"
            )
        if decision.suppression_active:
            reasons.append("post-fire suppression active")
        cooldown_ok = (now - self.behavior.last_emitted_at) >= self.config.classification_cooldown_seconds
        if not cooldown_ok:
            reasons.append(
                f"cooldown {self.config.classification_cooldown_seconds:.1f}s "
                f"({now - self.behavior.last_emitted_at:.1f}s elapsed)"
            )
        log.info(
            "Frame %d not classified: persons=%d carryables=%d -- %s",
            self.frame_seq,
            len(persons),
            len(carryables),
            "; ".join(reasons) or "no specific reason",
        )

    def _update_last_classification(self, event: dict[str, Any]) -> None:
        """Cache the latest Qwen output so the camera overlay can render it."""
        with self.state_lock:
            self.last_classification = LastClassification(
                timestamp=time.time(),
                tier=int(event.get("tier", 0)),
                behavior_pattern=str(event.get("behavior_pattern", "")),
                confidence=float(event.get("confidence", 0.0)),
                scene=str(event.get("scene", "")),
                suspect_description=str(event.get("suspect_description", "")),
                one_line_summary=str(event.get("one_line_summary", "")),
            )

    def _publish_event(self, event: dict[str, Any]) -> None:
        if not self.config.post_events:
            return
        event_payload = dict(event)
        if self.publisher_thread is None:
            self._publish_event_sync(event_payload)
            return
        try:
            self.publish_queue.put_nowait(event_payload)
        except queue.Full:
            log.warning(
                "Dropping event %s because event publisher is behind.",
                event_payload.get("event_id", "<unknown>"),
            )

    def _fire_theft_alert(self, event: dict[str, Any], frame_bgr: Any) -> None:
        """Hand a confirmed-theft event to the action router.

        Default path is in-process: theft_alert.trigger_theft_alert imports
        action_router.execute_action and runs the T4 EMERGENCY playbook
        directly on this machine — parallel Twilio voice calls + parallel
        iMessage fan-out via AppleScript on this Mac, with the suspect
        frame attached. No /upload, no second-Mac dependency.

        HTTP routing (POST to a remote action router) is opt-in via
        ACTION_ROUTER_USE_HTTP=true; theft_alert handles the branch.
        Legacy direct-publish fallback only fires if trigger_theft_alert
        itself raised, so dev/test still see something land at the router.
        """
        if not self.config.post_events:
            return
        try:
            trigger_theft_alert(
                frame_bgr=frame_bgr,
                incident_id=str(event.get("incident_id") or event.get("event_id", "")),
                suspect_description=str(event.get("suspect_description", "")),
                one_line_summary=str(event.get("one_line_summary", "")),
                scene=str(event.get("scene", "the camera view")),
                confidence=float(event.get("confidence", 0.6)),
                behavior_pattern=str(event.get("behavior_pattern", "taking_item")),
                yolo_classes=event.get("yolo_classes") or ["person"],
                time_elapsed=str(event.get("time_elapsed", "just now")),
            )
        except Exception as exc:
            log.warning(
                "trigger_theft_alert failed; falling back to legacy publisher: %s",
                exc,
            )
            self._publish_event(event)

    def _publish_event_sync(self, event: dict[str, Any]) -> None:
        try:
            result = post_event(event, self.config)
        except Exception as exc:
            log.warning("Action router POST failed: %s", exc)
            return

        if result.ok:
            self._router_url_warned = False
            try:
                payload = json.loads(result.body) if result.body else {}
            except (TypeError, ValueError):
                payload = {}
            calls = payload.get("calls") if isinstance(payload, dict) else None
            if isinstance(calls, list) and calls:
                first = calls[0] if isinstance(calls[0], dict) else {}
                _print_pretty_call(
                    str(first.get("to", "?")),
                    str(first.get("sid", "?")),
                )
            return

        self._log_router_delivery_issue(result)
        log.warning(
            "Action router returned %s for event %s: %s",
            result.status_code,
            event["event_id"],
            result.body,
        )

    def _log_router_delivery_issue(self, result: "PublishResult") -> None:
        if self._router_url_warned:
            return
        parsed = urlparse(self.config.action_router_url)
        host = parsed.netloc or parsed.path
        body_lower = result.body.lower()
        if "ngrok" in host and ("offline" in body_lower or "not found" in body_lower):
            log.error(
                "ACTION_ROUTER_URL is pointing at an offline ngrok endpoint: %s. "
                "Start the router and update ACTION_ROUTER_URL to a live /event URL.",
                self.config.action_router_url,
            )
            self._router_url_warned = True
            return
        if result.status_code == 404:
            log.error(
                "ACTION_ROUTER_URL returned 404: %s. Make sure the router is running "
                "and the URL ends with /event.",
                self.config.action_router_url,
            )
            self._router_url_warned = True

    @staticmethod
    def _throttle_loop(loop_started_at: float) -> None:
        elapsed = time.time() - loop_started_at
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _throttle_display_loop(loop_started_at: float) -> None:
        elapsed = time.time() - loop_started_at
        remaining = DISPLAY_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ThirdEye vision pipeline with YOLO11n and Qwen2-VL."
    )
    parser.add_argument(
        "--source",
        default=CONFIG.camera_source,
        help=(
            "Camera source. Use 0 for the local webcam, an RTSP/HTTP URL, "
            "or a `phone[:token]` shortcut to consume a paired phone camera "
            "(e.g. `phone`, `phone:lobby`)."
        ),
    )
    parser.add_argument(
        "--hide-window",
        action="store_true",
        help="Disable the OpenCV preview window.",
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        help="Print the event JSON but do not POST it to the action router.",
    )
    return parser


def _config_with(post_events: bool | None = None) -> Config:
    """Return CONFIG, overriding `post_events` if requested."""
    if post_events is None:
        return CONFIG
    return Config(
        node_id=CONFIG.node_id,
        camera_source=CONFIG.camera_source,
        capture_width=CONFIG.capture_width,
        capture_height=CONFIG.capture_height,
        yolo_model=CONFIG.yolo_model,
        yolo_input_size=CONFIG.yolo_input_size,
        yolo_input_size_busy=CONFIG.yolo_input_size_busy,
        qwen_model=CONFIG.qwen_model,
        qwen_max_new_tokens=CONFIG.qwen_max_new_tokens,
        qwen_min_pixels=CONFIG.qwen_min_pixels,
        qwen_max_pixels=CONFIG.qwen_max_pixels,
        qwen_frame_max_edge=CONFIG.qwen_frame_max_edge,
        qwen_frame_lookback_seconds=CONFIG.qwen_frame_lookback_seconds,
        pause_detection_while_classifying=CONFIG.pause_detection_while_classifying,
        classification_cooldown_seconds=CONFIG.classification_cooldown_seconds,
        action_router_url=CONFIG.action_router_url,
        person_confidence=CONFIG.person_confidence,
        carryable_confidence=CONFIG.carryable_confidence,
        post_timeout_seconds=CONFIG.post_timeout_seconds,
        post_events=post_events,
        event_queue_size=CONFIG.event_queue_size,
        show_window=CONFIG.show_window,
        mock_classifier=CONFIG.mock_classifier,
        debug_overlay=CONFIG.debug_overlay,
        debug_detections=CONFIG.debug_detections,
        save_failure_artifacts=CONFIG.save_failure_artifacts,
        debug_artifact_dir=CONFIG.debug_artifact_dir,
        artifact_queue_size=CONFIG.artifact_queue_size,
        entry_zone=CONFIG.entry_zone,
        use_entry_zone=CONFIG.use_entry_zone,
        carryable_labels=CONFIG.carryable_labels,
        cardboard_box_enable=CONFIG.cardboard_box_enable,
        cardboard_detector_backend=CONFIG.cardboard_detector_backend,
        yolo_world_model=CONFIG.yolo_world_model,
        yolo_world_input_size=CONFIG.yolo_world_input_size,
        yolo_world_confidence=CONFIG.yolo_world_confidence,
        yolo_world_cardboard_classes=CONFIG.yolo_world_cardboard_classes,
        cardboard_box_min_area_ratio=CONFIG.cardboard_box_min_area_ratio,
        cardboard_box_max_area_ratio=CONFIG.cardboard_box_max_area_ratio,
        cardboard_box_min_extent=CONFIG.cardboard_box_min_extent,
        cardboard_box_min_confidence=CONFIG.cardboard_box_min_confidence,
        cardboard_box_edge_margin_ratio=CONFIG.cardboard_box_edge_margin_ratio,
        cardboard_box_floor_min_y_ratio=CONFIG.cardboard_box_floor_min_y_ratio,
        cardboard_box_min_score=CONFIG.cardboard_box_min_score,
        interaction_frames_required=CONFIG.interaction_frames_required,
        min_dwell_seconds=CONFIG.min_dwell_seconds,
        carryable_grace_seconds=CONFIG.carryable_grace_seconds,
        stationary_object_min_seconds=CONFIG.stationary_object_min_seconds,
        removal_interaction_window_seconds=CONFIG.removal_interaction_window_seconds,
        stationary_object_distance_pixels=CONFIG.stationary_object_distance_pixels,
        person_min_area_ratio=CONFIG.person_min_area_ratio,
        edge_margin_ratio=CONFIG.edge_margin_ratio,
        person_exit_seconds=CONFIG.person_exit_seconds,
        scene_clear_seconds=CONFIG.scene_clear_seconds,
        pair_iou_threshold=CONFIG.pair_iou_threshold,
        pair_distance_ratio=CONFIG.pair_distance_ratio,
        anchor_seconds=CONFIG.anchor_seconds,
        move_px=CONFIG.move_px,
        move_iou=CONFIG.move_iou,
        package_missing_grace_seconds=CONFIG.package_missing_grace_seconds,
        person_near_package_window_seconds=CONFIG.person_near_package_window_seconds,
        interaction_window_seconds=CONFIG.interaction_window_seconds,
        feet_motion_enable=CONFIG.feet_motion_enable,
        feet_motion_min_area=CONFIG.feet_motion_min_area,
        theft_cooldown_seconds=CONFIG.theft_cooldown_seconds,
        demo_mode_theft_bias=CONFIG.demo_mode_theft_bias,
        qwen_frames_per_inference=CONFIG.qwen_frames_per_inference,
        demo_fast_path=CONFIG.demo_fast_path,
        demo_fast_path_cooldown_seconds=CONFIG.demo_fast_path_cooldown_seconds,
        capture_buffer_drain_grabs=CONFIG.capture_buffer_drain_grabs,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format=f"{_PRETTY_DIM}%(asctime)s{_PRETTY_RESET} %(message)s",
        datefmt="%H:%M:%S",
    )
    for _noisy in (
        "httpx",
        "huggingface_hub",
        "huggingface_hub.utils._http",
        "urllib3",
        "transformers",
        "ultralytics",
        "filelock",
    ):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    config = _config_with(post_events=False) if args.no_post else CONFIG

    engine = VisionEngine(
        config=config,
        source=parse_capture_source(args.source),
        show_window=False if args.hide_window else config.show_window,
    )
    engine.run()
