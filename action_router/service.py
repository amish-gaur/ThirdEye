"""FastAPI service: receives event JSON from the vision pipeline, runs the
router, and serves synthesized MP3s for Twilio to fetch."""

from __future__ import annotations

import logging
from typing import Any, Dict
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import CONFIG
from .router import execute_action
from .twiml import say_response

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

    @app.post("/voice/alert-response")
    async def receive_alert_response(request: Request) -> Response:
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(raw_body, keep_blank_values=True)
        digits = (form.get("Digits", [""])[0] or "").strip()
        call_sid = (form.get("CallSid", [""])[0] or "").strip()
        if digits == "1":
            log.info("Tier 3 IVR accepted neighbor notification request call_sid=%s", call_sid)
            twiml = say_response(
                "Neighbor notification request received. SafeWatch will continue monitoring. Goodbye."
            )
        elif digits == "2":
            log.info("Tier 3 IVR acknowledged ignore request call_sid=%s", call_sid)
            twiml = say_response("Understood. No additional action will be taken. Goodbye.")
        else:
            log.info("Tier 3 IVR received invalid input digits=%r call_sid=%s", digits, call_sid)
            twiml = say_response("No valid selection was received. Goodbye.")
        return Response(content=twiml, media_type="application/xml")

    return app


app = create_app()
