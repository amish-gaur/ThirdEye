"""Theft-alert wire to the action router.

The vision pipeline calls `trigger_theft_alert(...)` once per confirmed theft.
This module owns the I/O side (frame encode + upload + tier-4 event POST) so
`theft_tracker.py` stays a pure temporal state machine.

The action router lives on a separate Mac and is reached over ngrok via the
`ACTION_ROUTER_BASE_URL` env var. See WIRING_THEFT_DETECTOR.md for the full
contract.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
import requests


log = logging.getLogger("vision_pipeline.theft_alert")


# Reuse the action_router debug tracer so every step end-to-end is on a
# single tape. Imported lazily so a Linux / test environment that doesn't
# pull action_router still has a path through theft_alert.
try:
    from action_router._trace import trace as _trace, trace_exception as _trace_exc
except Exception:  # pragma: no cover — defensive: tracer must never break the demo
    def _trace(label, **kwargs):  # type: ignore[no-redef]
        pass

    def _trace_exc(label, exc, **kwargs):  # type: ignore[no-redef]
        pass


# Frames are written under <repo>/media/frames so they sit on the same disk
# as the rest of the pipeline's clip output. The /upload endpoint copies them
# onto the router's local fs and returns the absolute path to use as
# `clip_path` in the event payload.
_BEST_FRAME_DIR = Path(__file__).resolve().parent.parent / "media" / "frames"


def resolve_router_base_url() -> str | None:
    """Return the action router's base URL (no trailing slash, no /event).

    Prefers ACTION_ROUTER_BASE_URL (the spec env var). Falls back to
    ACTION_ROUTER_URL with the `/event` suffix stripped, since the
    legacy env var historically pointed at the full /event endpoint.
    Returns None when neither is set so callers can degrade gracefully.
    """
    base = os.environ.get("ACTION_ROUTER_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    legacy = os.environ.get("ACTION_ROUTER_URL", "").strip()
    if not legacy:
        return None
    legacy = legacy.rstrip("/")
    for suffix in ("/event", "/events"):
        if legacy.endswith(suffix):
            legacy = legacy[: -len(suffix)]
            break
    return legacy


def save_best_frame(frame_bgr: np.ndarray, incident_id: str) -> Path:
    """Persist the canonical 'this is the suspect' frame for an incident.

    Called once per incident at THEFT_CONFIRMED. JPEG-encodes at quality 92
    and returns the local path. The action router pulls this off disk
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
    base = resolve_router_base_url()
    if not base:
        raise RuntimeError(
            "ACTION_ROUTER_BASE_URL (or ACTION_ROUTER_URL) is not configured"
        )
    with local_path.open("rb") as f:
        r = requests.post(
            f"{base}/upload",
            files={"file": (local_path.name, f, "image/jpeg")},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["path"]


def _use_http() -> bool:
    """In-process is the default. Opt into HTTP via ACTION_ROUTER_USE_HTTP=true.

    In-process is more reliable for the demo: the frame is already on this
    Mac, Twilio creds are already in this .env, and Messages.app on this
    Mac drives the iMessage fan-out via AppleScript — so there's no
    /upload step, no second-Mac dependency, and no ngrok handshake. HTTP
    mode is kept for setups where the router runs on a separate machine.
    """
    return os.environ.get("ACTION_ROUTER_USE_HTTP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    """End-to-end: save best frame, fire tier-4 EMERGENCY action.

    Call once per confirmed theft (idempotent on `incident_id` — the router
    dedups within 3 minutes). Defaults to in-process execution: imports
    `action_router.execute_action` and calls it directly with the local
    frame path. HTTP fan-out (POST /upload then POST /event) is opt-in via
    `ACTION_ROUTER_USE_HTTP=true`.

    Returns the router's response dict (matches the JSON receipt format).
    """
    _trace(
        "THEFT_ALERT_ENTRY",
        level="BEGIN",
        incident=incident_id,
        confidence=confidence,
        scene=scene,
        suspect=suspect_description[:100],
        behavior=behavior_pattern,
    )
    frame_path = save_best_frame(frame_bgr, incident_id)
    try:
        size = frame_path.stat().st_size
    except OSError:
        size = -1
    _trace("FRAME_SAVED", level="OK", path=str(frame_path), bytes=size,
           shape=tuple(frame_bgr.shape) if hasattr(frame_bgr, "shape") else None)

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

    if _use_http():
        base = resolve_router_base_url()
        if not base:
            _trace("ROUTE", level="ERR",
                   reason="ACTION_ROUTER_USE_HTTP=true but no URL configured")
            raise RuntimeError(
                "ACTION_ROUTER_USE_HTTP=true but no router URL is configured"
            )
        _trace("ROUTE", level="STEP", mode="http", base=base)
        try:
            payload["clip_path"] = upload_frame_to_action_router(frame_path)
            _trace("UPLOAD_OK", level="OK", remote_path=payload["clip_path"])
        except Exception as exc:
            log.warning("frame upload failed; firing event without attachment: %s", exc)
            _trace_exc("UPLOAD_ERR", exc,
                       hint="firing event without clip_path; iMessage will be text-only")
        _trace("HTTP_POST_BEGIN", level="STEP", url=f"{base}/event",
               clip=payload.get("clip_path"))
        try:
            r = requests.post(f"{base}/event", json=payload, timeout=15)
            r.raise_for_status()
        except Exception as exc:
            _trace_exc("HTTP_POST_ERR", exc, url=f"{base}/event")
            raise
        body = r.json()
        _trace("HTTP_POST_OK", level="OK", status=r.status_code,
               actions=body.get("actions"))
        log.info("Fired theft alert (http): %s", body.get("actions"))
        return body

    # In-process path: frame stays local, AppleScript drives Messages.app
    # on this Mac, Twilio is called directly with creds in this .env.
    payload["clip_path"] = str(frame_path.resolve())
    _trace("ROUTE", level="STEP", mode="inproc", clip=payload["clip_path"])
    from action_router.router import execute_action  # local import — keeps cold imports fast

    result = execute_action(payload)
    body = result.to_dict()
    log.info("Fired theft alert (in-process): %s", body.get("actions"))
    _trace("THEFT_ALERT_DONE", level="OK", actions=body.get("actions"),
           calls=len(body.get("calls", [])),
           messages=len(body.get("messages", [])),
           errors=body.get("errors"))
    return body
