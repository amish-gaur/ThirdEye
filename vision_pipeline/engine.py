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

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from ultralytics import YOLO

from .config import CONFIG, Config
from .events import VISION_LANGUAGE_PROMPT, build_event, evaluate_classifier_output
from .publisher import post_event

FRAME_BUFFER_MAXLEN = 150
TARGET_FPS = 10
FRAME_INTERVAL_SECONDS = 1.0 / TARGET_FPS
PERSON_CLASS_ID = 0
BOX_CLASS_IDS = (24, 26, 28)  # backpack, handbag, suitcase
TRIGGER_CLASS_IDS = (PERSON_CLASS_ID,) + BOX_CLASS_IDS
CONSECUTIVE_PERSON_FRAMES = 2  # legacy export, behavior uses interaction_frames_required

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
    raw_source = raw_source.strip()
    if raw_source.isdigit():
        return int(raw_source)
    return raw_source


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
        primary_person: Detection | None = None
        for det in person_dets:
            if self.person_track is None or det.confidence > 0:
                self.person_track = TrackMemory(
                    last_seen_at=now,
                    last_box=det.box,
                    last_label="person",
                )
                primary_person = det
            if _point_in_zone(_box_center(det.box), zone, frame_size):
                person_in_zone_now = True
                if self.person_track is not None:
                    self.person_track.last_seen_in_zone_at = now
                primary_person = det

        for det in carryable_dets:
            mem = self.carryable_tracks.get(det.label)
            if mem is None:
                mem = TrackMemory(last_seen_at=now, last_box=det.box, last_label=det.label)
            else:
                mem.last_seen_at = now
                mem.last_box = det.box
                mem.last_label = det.label
            if _point_in_zone(_box_center(det.box), zone, frame_size):
                mem.last_seen_in_zone_at = now
            self.carryable_tracks[det.label] = mem

        # 2. Determine which carryables count as "still present" (grace window)
        active_carryable: tuple[str, TrackMemory] | None = None
        active_carryable_box: tuple[float, float, float, float] | None = None
        active_carryable_label: str | None = None
        for label, mem in self.carryable_tracks.items():
            if (now - mem.last_seen_at) <= self.carryable_grace_seconds and mem.last_box is not None:
                # Prefer the most recently seen carryable
                if active_carryable is None or mem.last_seen_at > active_carryable[1].last_seen_at:
                    active_carryable = (label, mem)
                    active_carryable_box = mem.last_box
                    active_carryable_label = label

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

        # 5. Update or build candidate
        interaction_signal = paired and person_in_zone_now
        if interaction_signal:
            if self.candidate is None:
                self.candidate = CandidateContext(
                    first_seen_at=now,
                    last_seen_at=now,
                )
            cand = self.candidate
            # Accumulate dwell from previous frame
            if self._last_frame_time > 0:
                dt = max(0.0, min(1.0, now - self._last_frame_time))
                cand.recent_zone_dwell += dt
            cand.last_seen_at = now
            cand.last_zone_seen_at = now
            cand.last_carryable_seen_at = now
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
        self.behavior = BehaviorTracker(config)
        self._artifact_dir_ensured = False
        # Demo-mode flag driving carryable label set
        self._carryable_label_set: set[str] = set(config.carryable_labels)
        # Latest Qwen output, surfaced on the camera overlay so you can SEE
        # what the model is saying about you in real time.
        self.last_classification = LastClassification()
        # Last time we fired a Qwen classification — used by the demo fast-path.
        self._last_fire_at: float = 0.0
        # Throttle for "why didn't this fire" debug log so we don't spam.
        self._last_fire_block_log_at: float = 0.0

        self.yolo = YOLO(config.yolo_model)
        self.yolo.to(self.device)

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

        if self.show_window:
            print("Vision engine running. Press 'q' in the preview window to quit.")
        else:
            print("Vision engine running without a preview window. Use Ctrl+C to quit.")

        try:
            while True:
                loop_started_at = time.time()

                ok, frame = cap.read()
                if not ok:
                    log.warning("Webcam / stream frame grab failed; retrying.")
                    self._throttle_loop(loop_started_at)
                    continue

                self.frame_seq += 1
                captured_at = time.time()
                self.frame_buffer.append(
                    BufferedFrame(timestamp=captured_at, frame_bgr=frame.copy())
                )

                fh, fw = frame.shape[:2]
                if self._classification_busy():
                    persons: list[Detection] = []
                    carryables: list[Detection] = []
                else:
                    persons, carryables = self._detect_persons_and_carryables(frame)

                decision = self.behavior.update(
                    now=captured_at,
                    person_dets=persons,
                    carryable_dets=carryables,
                    frame_size=(fw, fh),
                )

                if self.config.debug_detections:
                    log.info(
                        "frame=%d state=%s cues=%s persons=%s carryables=%s",
                        self.frame_seq,
                        decision.state,
                        decision.cues,
                        [(d.label, round(d.confidence, 2)) for d in persons],
                        [(d.label, round(d.confidence, 2)) for d in carryables],
                    )

                # Demo fast-path: if no fire in N seconds AND we see a person
                # right now, classify anyway. Means a punch / theft caught
                # outside the entry zone still triggers a call.
                fast_path = self._should_fast_path(persons, carryables, captured_at)
                should_fire = decision.should_classify or fast_path

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
                    if fast_path and not decision.should_classify:
                        log.info(
                            "Fast-path firing: %s with %s",
                            [d.label for d in persons],
                            [d.label for d in carryables] or "no carryable",
                        )
                    elif decision.candidate and decision.candidate.last_carryable_label:
                        log.info(
                            "Candidate firing: carryable=%s frames=%d dwell=%.2fs",
                            decision.candidate.last_carryable_label,
                            decision.candidate.interaction_frames,
                            decision.candidate.recent_zone_dwell,
                        )
                    latest_frame = self.frame_buffer[-1]

                    if self.config.mock_classifier:
                        parsed, raw = self._classify_with_qwen([frame], 0.0)
                        if parsed:
                            event = build_event(
                                classification=parsed,
                                node_id=self.config.node_id,
                                frame_seq=self.frame_seq,
                                yolo_classes=yolo_classes,
                                raw_classifier=raw,
                            )
                            self._update_last_classification(event)
                            print(json.dumps(event, ensure_ascii=True))
                            self._publish_event(event)
                        fired = True
                        self._last_fire_at = captured_at
                    else:
                        # Multi-frame: pass the most recent N frames so Qwen
                        # can see motion (a swing, a grab, a fall).
                        recent = self._collect_recent_frames(self.config.qwen_frames_per_inference)
                        request = ClassificationRequest(
                            timestamp=latest_frame.timestamp,
                            frame_seq=self.frame_seq,
                            frame_bgr=latest_frame.frame_bgr.copy(),
                            yolo_classes=yolo_classes,
                            extra_frames=recent[:-1],  # historical context
                        )
                        fired = self._submit_classification(request)
                        if fired:
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

                if self.show_window:
                    if self.config.debug_overlay:
                        with self.state_lock:
                            last_cls = self.last_classification
                        _draw_overlay(
                            frame,
                            config=self.config,
                            decision=decision,
                            last_classification=last_cls,
                        )
                    cv2.imshow("ThirdEye Vision Engine", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                self._throttle_loop(loop_started_at)
        finally:
            cap.release()
            if self.show_window:
                cv2.destroyAllWindows()
            self._stop_worker()

    # ---------------------------------------------------------------------
    # Detection helpers
    # ---------------------------------------------------------------------

    def _detected_classes(self, frame_bgr: Any) -> list[str]:
        """Legacy entry-point kept for tests + simple callers."""
        results = self.yolo.predict(
            source=frame_bgr,
            classes=[PERSON_CLASS_ID, *BOX_CLASS_IDS],
            conf=min(self.config.person_confidence, self.config.carryable_confidence),
            device=self.device,
            imgsz=self.config.yolo_input_size,
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
        results = self.yolo.predict(
            source=frame_bgr,
            classes=[PERSON_CLASS_ID, *BOX_CLASS_IDS],
            conf=lower_conf,
            device=self.device,
            imgsz=self.config.yolo_input_size,
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
        for cls_id, conf, xyxy in zip(cls_list, conf_list, xyxy_list):
            cls_id = int(cls_id)
            label = str(names.get(cls_id, str(cls_id))) if hasattr(names, "get") else str(names[cls_id])
            box = (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]))
            det = Detection(cls_id=cls_id, label=label, confidence=float(conf), box=box)
            if cls_id == PERSON_CLASS_ID:
                if det.confidence >= self.config.person_confidence:
                    persons.append(det)
            elif label in self._carryable_label_set:
                if det.confidence >= self.config.carryable_confidence:
                    carryables.append(det)
        return persons, carryables

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
                    continue

                event = build_event(
                    classification=parsed,
                    node_id=self.config.node_id,
                    frame_seq=request.frame_seq,
                    yolo_classes=request.yolo_classes,
                    raw_classifier=raw_answer,
                    timestamp=request.timestamp,
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
        if self._classification_busy():
            return False
        if (now - self._last_fire_at) < self.config.demo_fast_path_cooldown_seconds:
            return False
        return True

    def _collect_recent_frames(self, count: int) -> list[Any]:
        """Sample up to `count` frames from the rolling buffer (oldest first).

        Used to give Qwen multi-frame context. We sample evenly across the
        buffer so motion (a punch, a grab) is visible across the chosen frames.
        """
        if count <= 1 or len(self.frame_buffer) <= 1:
            return [self.frame_buffer[-1].frame_bgr.copy()] if self.frame_buffer else []
        buffered = list(self.frame_buffer)
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
            log.info(
                "Posted event %s to router (%s)",
                event["event_id"],
                result.status_code,
            )
            return

        log.warning(
            "Action router returned %s for event %s: %s",
            result.status_code,
            event["event_id"],
            result.body,
        )

    @staticmethod
    def _throttle_loop(loop_started_at: float) -> None:
        elapsed = time.time() - loop_started_at
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ThirdEye vision pipeline with YOLO11n and Qwen2-VL."
    )
    parser.add_argument(
        "--source",
        default=CONFIG.camera_source,
        help="Camera source. Use 0 for the local webcam or an RTSP URL.",
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
        qwen_model=CONFIG.qwen_model,
        qwen_max_new_tokens=CONFIG.qwen_max_new_tokens,
        qwen_min_pixels=CONFIG.qwen_min_pixels,
        qwen_max_pixels=CONFIG.qwen_max_pixels,
        qwen_frame_max_edge=CONFIG.qwen_frame_max_edge,
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
        carryable_labels=CONFIG.carryable_labels,
        interaction_frames_required=CONFIG.interaction_frames_required,
        min_dwell_seconds=CONFIG.min_dwell_seconds,
        carryable_grace_seconds=CONFIG.carryable_grace_seconds,
        person_exit_seconds=CONFIG.person_exit_seconds,
        scene_clear_seconds=CONFIG.scene_clear_seconds,
        pair_iou_threshold=CONFIG.pair_iou_threshold,
        pair_distance_ratio=CONFIG.pair_distance_ratio,
        demo_mode_theft_bias=CONFIG.demo_mode_theft_bias,
        qwen_frames_per_inference=CONFIG.qwen_frames_per_inference,
        demo_fast_path=CONFIG.demo_fast_path,
        demo_fast_path_cooldown_seconds=CONFIG.demo_fast_path_cooldown_seconds,
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
