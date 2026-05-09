"""Publish vision events into the action-router service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import CONFIG, Config


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
