"""Publish vision events into the action-router service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from .config import CONFIG, Config

log = logging.getLogger("vision_pipeline.publisher")


@dataclass(frozen=True)
class PublishResult:
    status_code: int
    ok: bool
    body: str


def post_event(
    event: dict[str, Any], config: Config = CONFIG
) -> PublishResult:
    response = requests.post(
        config.action_router_url,
        json=event,
        timeout=config.post_timeout_seconds,
    )
    return PublishResult(
        status_code=response.status_code,
        ok=response.ok,
        body=response.text,
    )


def post_ready_signal(config: Config = CONFIG) -> bool:
    """Tell the action router this camera engine has finished warming up.

    The router is tracking us as `status: warming` until this lands, then
    flips us to `status: running`. Demos use this to know when triggering
    a theft will actually be observed (vs. firing into a still-loading
    Qwen process).

    Best-effort: if the router is unreachable, the engine still works; we
    just don't appear ready in /api/cameras. Failure logs at DEBUG so a
    standalone `python -m vision_pipeline.engine` (no router) stays quiet.
    """
    try:
        base = config.action_router_url.rstrip("/")
        if base.endswith("/event"):
            base = base[: -len("/event")]
        url = f"{base}/internal/camera/ready"
        response = requests.post(
            url,
            json={"node_id": config.node_id},
            timeout=2.0,
        )
        if response.ok:
            return True
        log.debug("ready signal not accepted: status=%s body=%s", response.status_code, response.text[:200])
        return False
    except Exception:
        log.debug("ready signal post failed", exc_info=True)
        return False
