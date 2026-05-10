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
from typing import Any
from urllib.parse import urlparse

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from ultralytics import YOLO

from .config import CONFIG, Config
from .events import VISION_LANGUAGE_PROMPT, build_event, evaluate_classifier_output
from .publisher import post_event, post_ready_signal
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
class BehaviorDecision:
    state: str
    cues: list[str]
    should_classify: bool
    suppression_active: bool
    last_emitted_at: float
    candidate: CandidateContext | None
    person_boxes: list[Detection]
    carryable_boxes: list[Detection]
    near_miss: bool = False  # for failure-artifact saving


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


def _draw_overlay(
    frame_bgr: Any,
    *,
    config: Config,
    decision: BehaviorDecision,
    last_classification: "LastClassification | None" = None,
) -> None:
    h, w = frame_bgr.shape[:2]
    if config.use_entry_zone:
        zone = config.entry_zone
        x1, y1, x2, y2 = (
            int(zone[0] * w),
            int(zone[1] * h),
            int(zone[2] * w),
            int(zone[3] * h),
        )
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(frame_bgr, "ENTRY ZONE", (x1 + 4, y1 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1, cv2.LINE_AA)

    candidate = decision.candidate
    cand_person_box = candidate.last_person_box if candidate else None
    cand_carryable_box = candidate.last_carryable_box if candidate else None

    for det in decision.person_boxes:
        is_candidate = cand_person_box is not None and _box_iou(det.box, cand_person_box) > 0.3
        thickness = 3 if is_candidate else 2
        _draw_box(frame_bgr, det, color=(0, 255, 0), thickness=thickness)

    for det in decision.carryable_boxes:
        is_candidate = cand_carryable_box is not None and _box_iou(det.box, cand_carryable_box) > 0.3
        thickness = 3 if is_candidate else 2
        _draw_box(frame_bgr, det, color=(255, 80, 220), thickness=thickness)

    # Top-left status text
    lines = [
        f"state: {decision.state}",
        f"cues : {', '.join(decision.cues) if decision.cues else '-'}",
        f"suppress: {'ON' if decision.suppression_active else 'off'}"
        + (f"  demo_bias=ON" if config.demo_mode_theft_bias else ""),
        f"last_emit: {('%.1fs ago' % (time.time() - decision.last_emitted_at)) if decision.last_emitted_at else 'never'}",
    ]
    if candidate is not None:
        lines.append(
            f"cand: frames={candidate.interaction_frames} dwell={candidate.recent_zone_dwell:.2f}s carry={candidate.last_carryable_label}"
        )
    y = 22
    for line in lines:
        cv2.putText(frame_bgr, line, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame_bgr, line, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
        y += 22

    # Bottom panel: live Qwen description so you SEE what the model thinks of you.
    if last_classification is not None and last_classification.is_set:
        _draw_qwen_panel(frame_bgr, last_classification)


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


def _draw_box(frame_bgr: Any, det: Detection, *, color: tuple[int, int, int], thickness: int) -> None:
    x1, y1, x2, y2 = (int(v) for v in det.box)
    cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, thickness)
    label = f"{det.label} {det.confidence:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(frame_bgr, (x1, y1 - th - 6), (x1 + tw + 6, y1), color, -1)
    cv2.putText(frame_bgr, label, (x1 + 3, y1 - 4),
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
        self.classification_in_flight = False
        self.state_lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None
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

        self.yolo = YOLO(config.yolo_model)
        self.yolo.to(self.device)
        self._monitored_class_ids = self._resolve_monitored_class_ids()

        self.processor = None
        self.qwen = None
        if not self.config.mock_classifier:
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
                name="qwen-classifier",
                daemon=True,
            )
            self.worker_thread.start()
        log.info(
            "Vision engine ready device=%s source=%r yolo=%s qwen=%s capture=%sx%s "
            "person_conf=%s carryable_conf=%s zone=%s demo_bias=%s mock=%s post=%s overlay=%s artifacts=%s",
            self.device,
            self.source,
            self.config.yolo_model,
            self.config.qwen_model,
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

        # Tell the action router this engine is fully warmed up. Best-effort:
        # standalone runs (no router) silently no-op. The router uses this to
        # flip our /api/cameras entry from "warming" to "running" so demo
        # flows don't fire theft triggers into a still-loading Qwen process.
        if self.config.post_events:
            post_ready_signal(self.config)

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
            with self.decision_lock:
                self.latest_decision = decision

            if self.config.debug_detections:
                log.info(
                    "frame=%d state=%s cues=%s persons=%s carryables=%s",
                    self.frame_seq,
                    decision.state,
                    decision.cues,
                    [(d.label, round(d.confidence, 2)) for d in persons],
                    [(d.label, round(d.confidence, 2)) for d in carryables],
                )

            should_fire = theft_decision.should_emit

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
                log.info(
                    "Theft confirmed: state=%s package=%s cues=%s",
                    theft_decision.state,
                    theft_decision.anchor_label,
                    theft_decision.cues,
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
                    print(json.dumps(event, ensure_ascii=True))
                    self._publish_event(event)
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
            return [], []

        result = results[0]
        names = result.names
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return [], []

        cls_list = boxes.cls.tolist()
        try:
            conf_list = boxes.conf.tolist()
            xyxy_list = boxes.xyxy.tolist()
        except AttributeError:
            return [], []

        persons: list[Detection] = []
        carryables: list[Detection] = []
        if hasattr(frame_bgr, "shape") and len(frame_bgr.shape) >= 2:
            frame_h, frame_w = frame_bgr.shape[:2]
        else:
            frame_h, frame_w = self.config.capture_height, self.config.capture_width
        frame_size = (frame_w, frame_h)
        frame_area = float(frame_w * frame_h)
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
                print(json.dumps(event, ensure_ascii=True))
                self._publish_event(event)
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

    def _classification_busy(self) -> bool:
        with self.state_lock:
            return self.classification_in_flight

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
        try:
            dir_path = self._ensure_artifact_dir()
            ts = time.strftime("%Y%m%d-%H%M%S")
            stem = f"{ts}_{kind}_{uuid.uuid4().hex[:6]}"
            jpg_path = os.path.join(dir_path, stem + ".jpg")
            meta_path = os.path.join(dir_path, stem + ".json")
            cv2.imwrite(jpg_path, frame_bgr)
            cand = decision.candidate
            meta = {
                "kind": kind,
                "timestamp": time.time(),
                "frame_seq": self.frame_seq,
                "state": decision.state,
                "cues": decision.cues,
                "suppression_active": decision.suppression_active,
                "persons": [
                    {"conf": p.confidence, "box": list(p.box)} for p in persons
                ],
                "carryables": [
                    {"label": c.label, "conf": c.confidence, "box": list(c.box)}
                    for c in carryables
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
            log.exception("Failed to save failure artifact (kind=%s)", kind)

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
        if (now - self._last_fire_block_log_at) < 2.0:
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
        try:
            result = post_event(event, self.config)
        except Exception as exc:
            log.warning("Action router POST failed: %s", exc)
            return

        if result.ok:
            self._router_url_warned = False
            log.info(
                "Posted event %s to router (%s)",
                event["event_id"],
                result.status_code,
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
        show_window=CONFIG.show_window,
        mock_classifier=CONFIG.mock_classifier,
        debug_overlay=CONFIG.debug_overlay,
        debug_detections=CONFIG.debug_detections,
        save_failure_artifacts=CONFIG.save_failure_artifacts,
        debug_artifact_dir=CONFIG.debug_artifact_dir,
        entry_zone=CONFIG.entry_zone,
        use_entry_zone=CONFIG.use_entry_zone,
        carryable_labels=CONFIG.carryable_labels,
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
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config = _config_with(post_events=False) if args.no_post else CONFIG

    engine = VisionEngine(
        config=config,
        source=parse_capture_source(args.source),
        show_window=False if args.hide_window else config.show_window,
    )
    engine.run()
