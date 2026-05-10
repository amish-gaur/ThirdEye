"""Package-theft temporal state machine.

Theft decisions are made from YOLO detections + temporal rules only.
Qwen is used later to enrich descriptions after a theft is confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


STATE_IDLE = "IDLE"
STATE_PACKAGE_ANCHORED = "PACKAGE_ANCHORED"
STATE_PERSON_PRESENT = "PERSON_PRESENT"
STATE_PACKAGE_MOVED_OR_MISSING = "PACKAGE_MOVED_OR_MISSING"
STATE_THEFT_CONFIRMED = "THEFT_CONFIRMED"


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

        self.anchor_box: tuple[float, float, float, float] | None = None
        self.anchor_label: str | None = None
        self.anchor_created_at: float = 0.0
        self.anchor_last_seen_at: float = 0.0
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
                shift = _center_dist(self.anchor_box, matched.box)
                iou = _box_iou(self.anchor_box, matched.box)
                if shift > self.config.move_px or iou < self.config.move_iou:
                    self.state = STATE_PACKAGE_MOVED_OR_MISSING
                    cues.append("package_moved")
                else:
                    self.state = STATE_PACKAGE_ANCHORED
                self.anchor_box = matched.box
            elif (now - self.anchor_last_seen_at) > self.config.package_missing_grace_seconds:
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

        if self.anchor_box is not None and matched is None and self.state == STATE_PACKAGE_ANCHORED:
            if (now - self.anchor_last_seen_at) > max(
                self.config.package_missing_grace_seconds,
                self.config.person_near_package_window_seconds,
            ):
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
            self._pending_box = None
            self._pending_label = None
            self._pending_since = 0.0
            self.state = STATE_IDLE
            return

        strongest = max(package_dets, key=lambda d: d.confidence)
        if self._pending_box is None:
            self._pending_box = strongest.box
            self._pending_label = strongest.label
            self._pending_since = now
            self.state = STATE_IDLE
            return

        shift = _center_dist(self._pending_box, strongest.box)
        if shift > (self.config.move_px * 0.5):
            self._pending_box = strongest.box
            self._pending_label = strongest.label
            self._pending_since = now
            self.state = STATE_IDLE
            return

        if (now - self._pending_since) >= self.config.anchor_seconds:
            self.anchor_box = strongest.box
            self.anchor_label = strongest.label
            self.anchor_created_at = now
            self.anchor_last_seen_at = now
            self.anchor_emitted = False
            self.state = STATE_PACKAGE_ANCHORED

    def _match_anchor(self, package_dets: list[PackageDetection]) -> PackageDetection | None:
        if self.anchor_box is None or not package_dets:
            return None
        return min(package_dets, key=lambda d: _center_dist(self.anchor_box, d.box))

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
        self.anchor_emitted = False
        self.last_person_near_at = 0.0
        self.state = STATE_IDLE
