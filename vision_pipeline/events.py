"""Shared event schema + classifier output parsing for the vision side."""

from __future__ import annotations

import ast
import json
import re
import time
import uuid
from typing import Any

VISION_LANGUAGE_PROMPT = """You are a neighborhood security classifier. Analyze the scene.

Return JSON: {'tier': [1, 2, 3, or 4], 'confidence': float, 'suspect_description': 'string', 'one_line_summary': 'string', 'time_elapsed': 'string'}."""

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

REQUIRED_CLASSIFIER_KEYS = {
    "tier",
    "confidence",
    "suspect_description",
    "one_line_summary",
    "time_elapsed",
}


def extract_json_object(raw_text: str) -> str | None:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None

    return match.group(0)


def parse_classifier_output(
    raw_text: str, time_elapsed_seconds: float
) -> dict[str, Any] | None:
    json_blob = extract_json_object(raw_text)
    if json_blob is None:
        return None

    payload = _load_structured_payload(json_blob)
    if payload is None:
        return None

    return _normalize_classifier_payload(payload, time_elapsed_seconds)


def build_event(
    *,
    classification: dict[str, Any],
    node_id: str,
    frame_seq: int,
    yolo_classes: list[str],
    raw_classifier: str,
    timestamp: float | None = None,
) -> dict[str, Any]:
    tier = int(classification["tier"])
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "node_id": node_id,
        "tier": tier,
        "tier_name": TIER_LABELS.get(tier, "UNKNOWN"),
        "confidence": float(classification["confidence"]),
        "suspect_description": classification["suspect_description"],
        "one_line_summary": classification["one_line_summary"],
        "time_elapsed": classification["time_elapsed"],
        "timestamp": timestamp if timestamp is not None else time.time(),
        "frame_seq": frame_seq,
        "yolo_classes": sorted(set(yolo_classes)),
        "clip_hash": None,
        "raw_classifier": raw_classifier,
    }


def _load_structured_payload(blob: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(blob)
        except (ValueError, SyntaxError):
            return None

    if not isinstance(payload, dict):
        return None

    return payload


def _normalize_classifier_payload(
    payload: dict[str, Any], time_elapsed_seconds: float
) -> dict[str, Any] | None:
    if not REQUIRED_CLASSIFIER_KEYS.issubset(payload.keys()):
        return None

    try:
        tier = int(payload["tier"])
        confidence = float(payload["confidence"])
    except (TypeError, ValueError):
        return None

    if tier not in {1, 2, 3, 4}:
        return None

    suspect_description = payload["suspect_description"]
    one_line_summary = payload["one_line_summary"]
    time_elapsed = payload["time_elapsed"]
    if not isinstance(suspect_description, str):
        return None
    if not isinstance(one_line_summary, str):
        return None
    if not isinstance(time_elapsed, str):
        return None

    return {
        "tier": tier,
        "confidence": confidence,
        "suspect_description": suspect_description.strip(),
        "one_line_summary": one_line_summary.strip(),
        "time_elapsed": f"{time_elapsed_seconds:.2f}s",
    }
