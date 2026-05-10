"""FastAPI app factory for the phone-infra lane.

Mounts:
    /inbound/voice*       — Twilio webhooks (this lane)
    /voice/state/*        — cross-lane voice state machine

The action_router lives in its own service. This app is independent so it
can be deployed behind its own ngrok subdomain when Twilio webhooks need a
stable public URL while we iterate on the action router separately.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from ..voice_state.api import router as voice_state_router
from .config import CONFIG
from .webhook import router as webhook_router

log = logging.getLogger("inbound_voice.app")


def create_app() -> FastAPI:
    app = FastAPI(title="ThirdEye — Phone Infra")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "twilio_configured": CONFIG.has_twilio(),
            "kms_configured": CONFIG.has_kms_key(),
            "rishab_agent_configured": bool(CONFIG.rishab_agent_ws_url),
        }

    app.include_router(webhook_router)
    app.include_router(voice_state_router)
    return app


app = create_app()
