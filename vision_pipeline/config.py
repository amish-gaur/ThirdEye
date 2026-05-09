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


@dataclass(frozen=True)
class Config:
    node_id: str = os.getenv("NODE_ID", "node_local")
    camera_source: str = os.getenv("CAMERA_SOURCE", "0")
    capture_width: int = _int("CAPTURE_WIDTH", 640)
    capture_height: int = _int("CAPTURE_HEIGHT", 480)
    yolo_model: str = os.getenv("YOLO_MODEL", "yolo11n.pt")
    yolo_input_size: int = _int("YOLO_INPUT_SIZE", 640)
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
    person_confidence: float = _float("PERSON_CONFIDENCE", 0.35)
    post_timeout_seconds: float = _float("POST_TIMEOUT_SECONDS", 10.0)
    post_events: bool = _bool("POST_EVENTS", True)
    show_window: bool = _bool("SHOW_WINDOW", True)
    mock_classifier: bool = _bool("MOCK_CLASSIFIER", False)


CONFIG = Config()
