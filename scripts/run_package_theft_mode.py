"""Launch SafeWatch with package-theft optimized defaults.

This helper sets practical environment defaults so users can run a focused
package-theft detector without hand-tuning dozens of flags.
"""

from __future__ import annotations

import os

from vision_pipeline.engine import main


def _setdefault(key: str, value: str) -> None:
    if not os.getenv(key):
        os.environ[key] = value


def apply_package_theft_defaults() -> None:
    # Focus all downstream logic on porch/package theft workflows.
    _setdefault("PACKAGE_THEFT_ONLY", "true")
    _setdefault("PACKAGE_THEFT_ALERT_PATTERNS", "taking_item,opening_container,fleeing")
    _setdefault("USE_ENTRY_ZONE", "false")
    _setdefault("ENTRY_ZONE", "0,0,1,1")

    # Bias behavior tracker toward catching pickup/removal cues quickly.
    _setdefault("DEMO_MODE_THEFT_BIAS", "true")
    _setdefault("DEMO_FAST_PATH", "true")
    _setdefault("DEMO_FAST_PATH_COOLDOWN_SECONDS", "5.0")

    # Practical defaults for porch/package objects.
    _setdefault("CARRYABLE_LABELS", "backpack,handbag,suitcase,cell phone,laptop")
    _setdefault("PERSON_CONFIDENCE", "0.40")
    _setdefault("CARRYABLE_CONFIDENCE", "0.25")
    # Keep the live preview smooth when Qwen is active.
    _setdefault("YOLO_INPUT_SIZE_BUSY", "512")
    _setdefault("CAPTURE_BUFFER_DRAIN_GRABS", "2")
    _setdefault("PAUSE_DETECTION_WHILE_CLASSIFYING", "true")
    _setdefault("QWEN_MAX_NEW_TOKENS", "64")
    # Make theft sequence detection robust to occasional dropped detections.
    _setdefault("ANCHOR_SECONDS", "0.4")
    _setdefault("MOVE_PX", "24")
    _setdefault("MOVE_IOU", "0.60")
    _setdefault("PACKAGE_MISSING_GRACE_SECONDS", "1.2")
    _setdefault("PERSON_NEAR_PACKAGE_WINDOW_SECONDS", "3.0")
    _setdefault("INTERACTION_WINDOW_SECONDS", "4.0")
    _setdefault("FEET_MOTION_ENABLE", "true")
    _setdefault("FEET_MOTION_MIN_AREA", "900")
    _setdefault("THEFT_COOLDOWN_SECONDS", "8.0")

    # Keep alerting responsive for theft scenes.
    _setdefault("ALERT_CONFIDENCE_FLOOR", "0.30")
    _setdefault("EMERGENCY_CONFIDENCE_FLOOR", "0.50")


if __name__ == "__main__":
    apply_package_theft_defaults()
    main()
