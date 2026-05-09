"""Shared event fixtures for smoke-test scripts and unit tests."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

DEFAULT_SUMMARIES = {
    1: "Someone walked past the porch.",
    2: "Someone has been on your porch for three minutes.",
    3: "took a package from the porch",
    4: "Resident has fallen and is not moving.",
}

DEFAULT_BEHAVIOR_PATTERNS = {
    1: "walking_through",
    2: "loitering",
    3: "taking_item",
    4: "collapsed",
}


def sample_event(
    tier: int = 3,
    description: str = "young man in a red hoodie and dark jeans",
    summary: str | None = None,
    confidence: float = 0.82,
    behavior_pattern: str | None = None,
) -> Dict[str, Any]:
    summary = summary or DEFAULT_SUMMARIES.get(tier, "Activity at your home.")
    pattern = behavior_pattern or DEFAULT_BEHAVIOR_PATTERNS.get(tier, "other_benign")
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "node_id": "node_local",
        "tier": tier,
        "tier_name": TIER_LABELS.get(tier, "UNKNOWN"),
        "confidence": confidence,
        "behavior_pattern": pattern,
        "suspect_description": description,
        "one_line_summary": summary,
        "time_elapsed": "just now",
        "timestamp": time.time(),
        "frame_seq": 4321,
        "yolo_classes": ["person", "backpack"] if tier >= 3 else ["person"],
        "clip_hash": None,
        "raw_classifier": "",
    }
