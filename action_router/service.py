"""FastAPI service: receives event JSON from the vision pipeline, runs the
router, and serves synthesized MP3s for Twilio to fetch."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .router import execute_action

log = logging.getLogger("action_router.service")


def create_app() -> FastAPI:
    app = FastAPI(title="SafeWatch Action Router")

    media_dir = CONFIG.ensure_media_dir()
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "dry_run": CONFIG.dry_run,
            "use_claude": CONFIG.use_claude,
            "use_elevenlabs": CONFIG.use_elevenlabs,
            "elevenlabs_play_enabled": CONFIG.elevenlabs_play_enabled(),
            "public_base_url": CONFIG.public_base_url,
            "twilio_configured": bool(CONFIG.twilio_account_sid),
        }

    @app.post("/event")
    async def receive_event(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        log.info(
            "Received event tier=%s summary=%r",
            payload.get("tier"),
            payload.get("one_line_summary"),
        )
        result = execute_action(payload)
        return JSONResponse(result.to_dict())

    return app


app = create_app()
