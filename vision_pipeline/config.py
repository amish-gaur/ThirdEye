"""Environment-backed config for the vision pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _str(key: str, default: str) -> str:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw


def _zone(key: str, default: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Parse a normalized rect 'x1,y1,x2,y2' (each in [0,1]) from env."""
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        parts = [float(p.strip()) for p in raw.split(",")]
        if len(parts) != 4:
            return default
        x1, y1, x2, y2 = parts
        return (x1, y1, x2, y2)
    except ValueError:
        return default


# Carryable / removable label set (configurable via env
# CARRYABLE_LABELS="backpack,handbag,suitcase,laptop,cell phone")
def _label_set(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(key)
    if not raw:
        return default
    items = tuple(s.strip() for s in raw.split(",") if s.strip())
    return items or default


@dataclass(frozen=True)
class Config:
    node_id: str = os.getenv("NODE_ID", "node_local")
    camera_source: str = os.getenv("CAMERA_SOURCE", "0")
    capture_width: int = _int("CAPTURE_WIDTH", 640)
    capture_height: int = _int("CAPTURE_HEIGHT", 480)
    yolo_model: str = os.getenv("YOLO_MODEL", "yolo11n.pt")
    yolo_input_size: int = _int("YOLO_INPUT_SIZE", 640)
    # When Qwen classification is in-flight on MPS, reduce YOLO imgsz to keep
    # the preview loop responsive. 0/negative disables the busy-size override.
    yolo_input_size_busy: int = _int("YOLO_INPUT_SIZE_BUSY", 512)
    qwen_model: str = os.getenv("QWEN_MODEL", "Qwen/Qwen2-VL-2B-Instruct")
    qwen_max_new_tokens: int = _int("QWEN_MAX_NEW_TOKENS", 96)
    qwen_min_pixels: int = _int("QWEN_MIN_PIXELS", 256 * 28 * 28)
    qwen_max_pixels: int = _int("QWEN_MAX_PIXELS", 512 * 28 * 28)
    qwen_frame_max_edge: int = _int("QWEN_FRAME_MAX_EDGE", 512)
    classification_cooldown_seconds: float = _float(
        "CLASSIFICATION_COOLDOWN_SECONDS", 8.0
    )
    action_router_url: str = os.getenv(
        "ACTION_ROUTER_URL", "http://127.0.0.1:8001/event"
    )
    person_confidence: float = _float("PERSON_CONFIDENCE", 0.45)
    carryable_confidence: float = _float("CARRYABLE_CONFIDENCE", 0.25)
    post_timeout_seconds: float = _float("POST_TIMEOUT_SECONDS", 10.0)
    post_events: bool = _bool("POST_EVENTS", True)
    event_queue_size: int = _int("EVENT_QUEUE_SIZE", 16)
    show_window: bool = _bool("SHOW_WINDOW", True)
    mock_classifier: bool = _bool("MOCK_CLASSIFIER", False)

    # Debug + observability
    debug_overlay: bool = _bool("DEBUG_OVERLAY", True)
    debug_detections: bool = _bool("DEBUG_DETECTIONS", False)
    save_failure_artifacts: bool = _bool("SAVE_FAILURE_ARTIFACTS", False)
    debug_artifact_dir: str = _str("DEBUG_ARTIFACT_DIR", "./debug_vision")
    artifact_queue_size: int = _int("ARTIFACT_QUEUE_SIZE", 16)

    # Entry zone, normalized [0,1] coordinates: x1, y1, x2, y2
    entry_zone: tuple[float, float, float, float] = _zone(
        "ENTRY_ZONE", (0.10, 0.20, 0.90, 0.95)
    )
    # If false, ignore entry-zone gating and use full-frame logic.
    use_entry_zone: bool = _bool("USE_ENTRY_ZONE", False)

    # Carryable label set
    carryable_labels: tuple[str, ...] = _label_set(
        "CARRYABLE_LABELS", ("backpack", "handbag", "suitcase", "laptop", "cell phone")
    )

    # Cardboard package detection. COCO YOLO models usually do not expose a
    # "cardboard box" class. Package-theft mode can use YOLO-World for an
    # open-vocabulary cardboard-box prompt, with the OpenCV color/shape detector
    # kept as a fallback backend.
    cardboard_box_enable: bool = _bool("CARDBOARD_BOX_ENABLE", True)
    cardboard_detector_backend: str = _str("CARDBOARD_DETECTOR_BACKEND", "opencv")
    yolo_world_model: str = _str("YOLO_WORLD_MODEL", "yolov8s-world.pt")
    yolo_world_input_size: int = _int("YOLO_WORLD_INPUT_SIZE", 640)
    yolo_world_confidence: float = _float("YOLO_WORLD_CONFIDENCE", 0.10)
    yolo_world_cardboard_classes: tuple[str, ...] = _label_set(
        "YOLO_WORLD_CARDBOARD_CLASSES", ("cardboard box", "shipping box")
    )
    cardboard_box_min_area_ratio: float = _float("CARDBOARD_BOX_MIN_AREA_RATIO", 0.006)
    cardboard_box_max_area_ratio: float = _float("CARDBOARD_BOX_MAX_AREA_RATIO", 0.25)
    cardboard_box_min_extent: float = _float("CARDBOARD_BOX_MIN_EXTENT", 0.45)
    cardboard_box_min_confidence: float = _float("CARDBOARD_BOX_MIN_CONFIDENCE", 0.32)
    cardboard_box_edge_margin_ratio: float = _float("CARDBOARD_BOX_EDGE_MARGIN_RATIO", 0.005)
    cardboard_box_floor_min_y_ratio: float = _float("CARDBOARD_BOX_FLOOR_MIN_Y_RATIO", 0.60)
    cardboard_box_min_score: float = _float("CARDBOARD_BOX_MIN_SCORE", 0.16)

    # Behavior tuning
    interaction_frames_required: int = _int("INTERACTION_FRAMES_REQUIRED", 4)
    min_dwell_seconds: float = _float("MIN_DWELL_SECONDS", 0.6)
    carryable_grace_seconds: float = _float("CARRYABLE_GRACE_SECONDS", 0.6)
    stationary_object_min_seconds: float = _float("STATIONARY_OBJECT_MIN_SECONDS", 1.0)
    removal_interaction_window_seconds: float = _float(
        "REMOVAL_INTERACTION_WINDOW_SECONDS", 2.0
    )
    stationary_object_distance_pixels: float = _float(
        "STATIONARY_OBJECT_DISTANCE_PIXELS", 48.0
    )
    person_min_area_ratio: float = _float("PERSON_MIN_AREA_RATIO", 0.015)
    edge_margin_ratio: float = _float("EDGE_MARGIN_RATIO", 0.04)
    person_exit_seconds: float = _float("PERSON_EXIT_SECONDS", 1.5)
    scene_clear_seconds: float = _float("SCENE_CLEAR_SECONDS", 3.5)
    pair_iou_threshold: float = _float("PAIR_IOU_THRESHOLD", 0.0)
    pair_distance_ratio: float = _float("PAIR_DISTANCE_RATIO", 1.5)

    # Demo mode: bias toward catching theft cues quickly during live demos
    demo_mode_theft_bias: bool = _bool("DEMO_MODE_THEFT_BIAS", False)

    # Qwen multi-frame inference: pass the most recent N frames (1-4) so the
    # model can see motion (punching, grabbing, fleeing). 1 = single-frame.
    qwen_frames_per_inference: int = _int("QWEN_FRAMES_PER_INFERENCE", 3)
    qwen_frame_lookback_seconds: float = _float("QWEN_FRAME_LOOKBACK_SECONDS", 1.2)
    # To keep UI smooth on Apple Silicon, pause YOLO passes while a Qwen
    # classification is running on MPS.
    pause_detection_while_classifying: bool = _bool(
        "PAUSE_DETECTION_WHILE_CLASSIFYING", True
    )

    # Demo fast-path: classify on any person sighting if the behavior tracker
    # hasn't fired in N seconds. Trades some precision for reliability so demos
    # don't silently miss events outside the entry zone.
    demo_fast_path: bool = _bool("DEMO_FAST_PATH", True)
    demo_fast_path_cooldown_seconds: float = _float(
        "DEMO_FAST_PATH_COOLDOWN_SECONDS", 6.0
    )

    # Package-theft temporal state machine knobs
    anchor_seconds: float = _float("ANCHOR_SECONDS", 0.8)
    move_px: float = _float("MOVE_PX", 36.0)
    move_iou: float = _float("MOVE_IOU", 0.35)
    package_missing_grace_seconds: float = _float(
        "PACKAGE_MISSING_GRACE_SECONDS", 0.8
    )
    person_near_package_window_seconds: float = _float(
        "PERSON_NEAR_PACKAGE_WINDOW_SECONDS", 2.0
    )
    interaction_window_seconds: float = _float("INTERACTION_WINDOW_SECONDS", 2.2)
    feet_motion_enable: bool = _bool("FEET_MOTION_ENABLE", True)
    feet_motion_min_area: float = _float("FEET_MOTION_MIN_AREA", 1800.0)
    theft_cooldown_seconds: float = _float("THEFT_COOLDOWN_SECONDS", 8.0)
    # Drop buffered camera frames before decode to reduce display latency when
    # inference gets briefly overloaded.
    capture_buffer_drain_grabs: int = _int("CAPTURE_BUFFER_DRAIN_GRABS", 2)


CONFIG = Config()
