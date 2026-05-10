"""FastAPI service: receives event JSON from the vision pipeline, runs the
router, and serves synthesized MP3s + uploaded incident frames for Twilio
and iMessage to fetch."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List
from urllib.parse import parse_qs

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import disambiguate, return_log
from .amazon_return_agent import initiate_return
from .claude_identifier import install as install_claude_identifier
from .config import CONFIG
from .discovery_routes import create_discovery_router
from .identity import get_identity_store
from .router import execute_action
from .twiml import say_response

log = logging.getLogger("action_router.service")


# In-process pub/sub for SSE event stream. Each connected UI client gets its
# own bounded asyncio.Queue; the /event handler fans out to all of them. The
# bound caps memory if a client stalls — old events drop rather than back up.
_event_subscribers: List[asyncio.Queue] = []
_subscribers_lock = asyncio.Lock()


async def _broadcast_event(payload: Dict[str, Any]) -> None:
    async with _subscribers_lock:
        targets = list(_event_subscribers)
    for q in targets:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            log.warning("SSE subscriber queue full; dropping event")


def create_app() -> FastAPI:
    app = FastAPI(title="ThirdEye Action Router")

    # Permissive CORS so the figma-ui dev server (vite on localhost:3000+) and
    # any LAN client can hit the API directly. Tighten if this ever ships
    # outside the demo box.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    media_dir = CONFIG.ensure_media_dir()
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    # Activate the vision-based identifier (replaces the env-var stub).
    # Safe to call even if the orders cache is empty — identifier will
    # return PackageMatch.empty() and the router falls back to evidence-only.
    try:
        install_claude_identifier()
    except Exception:
        log.exception("claude_identifier install failed; falling back to stub")

    # LAN camera discovery (mDNS) + camera-subprocess registry.
    discovery_router = create_discovery_router()
    app.include_router(discovery_router)
    camera_registry = discovery_router.state_registry  # type: ignore[attr-defined]

    identity_store = get_identity_store()

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

    # ─── Identity (phone → web handoff) ──────────────────────────────────
    # Phone POSTs identity → backend mints a 6-digit code → web claims it.
    # See action_router/identity.py for the storage contract.

    @app.post("/api/identity")
    async def identity_submit(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid json: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        try:
            session = identity_store.submit(
                name=str(payload.get("name", "")),
                email=str(payload.get("email", "")),
                device_id=payload.get("device_id"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return JSONResponse(session.to_dict(), status_code=201)

    @app.get("/api/identity/by-code/{code}")
    async def identity_by_code(code: str) -> JSONResponse:
        session = identity_store.get_by_code(code)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown or expired code")
        return JSONResponse(session.to_dict())

    @app.post("/api/identity/by-code/{code}/claim")
    async def identity_claim(code: str) -> JSONResponse:
        session = identity_store.claim(code)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown or expired code")
        return JSONResponse(session.to_dict())

    # ─── Warmup ──────────────────────────────────────────────────────────
    # Truthful readiness signal: the vision engine only POSTs ready after
    # it has loaded YOLO, Qwen weights, processor caches, and run a
    # throwaway inference (`_prewarm()` in vision_pipeline/engine.py).
    # That flips the registry entry from `warming` → `running`. So
    # `state == "ready"` here is equivalent to "your first real frame
    # will not pay a cold-start tax."

    @app.get("/api/warmup")
    def warmup_status() -> Dict[str, Any]:
        entries = camera_registry.active()
        running = [e for e in entries if e.status == "running"]
        warming = [e for e in entries if e.status == "warming"]
        crashed = [e for e in entries if e.status == "crashed"]

        if running:
            state = "ready"
            elapsed = max(
                (e.ready_at - e.started_at) for e in running if e.ready_at
            ) if any(e.ready_at for e in running) else 0.0
        elif warming:
            state = "warming"
            elapsed = max(time.time() - e.started_at for e in warming)
        else:
            state = "cold"
            elapsed = 0.0

        return {
            "state": state,
            "elapsed_s": round(elapsed, 2),
            "running": len(running),
            "warming": len(warming),
            "crashed": len(crashed),
            "nodes": [e.to_dict() for e in entries],
        }

    @app.post("/api/warmup")
    def warmup_trigger() -> Dict[str, Any]:
        """Idempotent — vision pipeline already runs on `make run`. We
        return the live state so the caller (phone during onboarding)
        can poll for `ready` without a separate GET first."""
        return warmup_status()

    _SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")

    @app.post("/upload")
    async def upload_frame(file: UploadFile = File(...)) -> JSONResponse:
        """Save an incident frame (or any blob) to MEDIA_DIR and return its
        absolute path on this machine plus the public URL.

        Two callers in the cross-Mac demo setup:
        * Vision pipeline (Amish's Mac) uploads the best frame of a
          confirmed theft so the iMessage attachment fires from the host
          Mac (Aditya's) where Messages.app is signed in.
        * Vision pipeline can also upload short clips (mp4) the same way;
          the returned `path` is what `clip_path` should be set to in the
          subsequent /event POST so `_fanout_imessage` finds the file
          locally on this Mac.

        Filename is sanitized + prefixed with a random hex segment to
        prevent collisions and traversal."""
        original = file.filename or "frame.bin"
        original = original.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        safe = _SAFE_FILENAME.sub("_", original)[:80] or "frame.bin"
        unique = f"{uuid.uuid4().hex[:8]}_{safe}"
        out = CONFIG.ensure_media_dir() / unique
        contents = await file.read()
        out.write_bytes(contents)
        log.info("upload saved %s (%d bytes)", out, len(contents))
        return JSONResponse({
            "path": str(out.resolve()),
            "url": CONFIG.media_url(unique),
            "size": len(contents),
            "filename": unique,
        })

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
        result_dict = result.to_dict()
        # Fan out to UI subscribers. Merge raw event + router decision so the
        # UI gets tier/summary/node plus action outcomes in one shape.
        await _broadcast_event({"event": payload, "result": result_dict})
        return JSONResponse(result_dict)

    @app.get("/events/stream")
    async def events_stream(request: Request) -> StreamingResponse:
        """SSE feed of every event POSTed to /event. The UI subscribes via
        EventSource and renders each message as an incident row."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        async with _subscribers_lock:
            _event_subscribers.append(queue)

        async def gen():
            try:
                # Initial comment so EventSource fires `open` immediately.
                yield ": connected\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(item)}\n\n"
                    except asyncio.TimeoutError:
                        # Keepalive comment — keeps proxies from closing idle.
                        yield ": keepalive\n\n"
            finally:
                async with _subscribers_lock:
                    if queue in _event_subscribers:
                        _event_subscribers.remove(queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/voice/alert-response")
    async def receive_alert_response(request: Request) -> Response:
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(raw_body, keep_blank_values=True)
        digits = (form.get("Digits", [""])[0] or "").strip()
        call_sid = (form.get("CallSid", [""])[0] or "").strip()
        if digits == "1":
            log.info("Tier 3 IVR accepted neighbor notification request call_sid=%s", call_sid)
            twiml = say_response(
                "Neighbor notification request received. ThirdEye will continue monitoring. Goodbye."
            )
        elif digits == "2":
            log.info("Tier 3 IVR acknowledged ignore request call_sid=%s", call_sid)
            twiml = say_response("Understood. No additional action will be taken. Goodbye.")
        else:
            log.info("Tier 3 IVR received invalid input digits=%r call_sid=%s", digits, call_sid)
            twiml = say_response("No valid selection was received. Goodbye.")
        return Response(content=twiml, media_type="application/xml")

    @app.post("/sms/inbound")
    async def receive_inbound_sms(request: Request) -> Response:
        """Twilio inbound SMS webhook.

        Two flows resolve here:
        - STOP-style reply within the undo window cancels the most recent
          auto-return.
        - Numeric reply ("1", "2", "3") or "N" resolves the most recent ASK
          decision into a concrete order, and we then drive the return.
        """
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(raw_body, keep_blank_values=True)
        body_text = (form.get("Body", [""])[0] or "").strip()
        from_number = (form.get("From", [""])[0] or "").strip()
        log.info("inbound sms from=%s body=%r", from_number, body_text)

        # 1) STOP / undo: cancels the most recent auto-return.
        if disambiguate.is_stop_reply(body_text):
            pending = disambiguate.latest_pending_of("undo")
            if pending is None:
                return Response(content="<Response/>", media_type="application/xml")
            disambiguate.resolve(pending.incident_id, "stop")
            return_log.append(
                {
                    "incident_id": pending.incident_id,
                    "decision": "auto_undo",
                    "order_id": pending.auto_order_id,
                    "note": "homeowner replied STOP within undo window",
                }
            )
            log.info(
                "Auto-return marked for cancellation incident=%s order=%s",
                pending.incident_id,
                pending.auto_order_id,
            )
            # NOTE: actually reversing the Amazon return is a separate
            # browser flow (cancel return). Codev / a follow-up ticket can
            # add that. For now we record the intent and let the homeowner
            # cancel manually if needed.
            return Response(content="<Response/>", media_type="application/xml")

        # 2) Disambiguation reply.
        pending = disambiguate.latest_pending_of("ask")
        if pending is None:
            return Response(content="<Response/>", media_type="application/xml")
        order_id = disambiguate.parse_ask_reply(body_text, pending.candidates)
        if order_id is None:
            disambiguate.resolve(pending.incident_id, "stop" if body_text else "ignored")
            return_log.append(
                {
                    "incident_id": pending.incident_id,
                    "decision": "ask_declined",
                    "reply": body_text,
                }
            )
            return Response(content="<Response/>", media_type="application/xml")

        disambiguate.resolve(pending.incident_id, f"picked:{order_id}")
        picked = next((c for c in pending.candidates if c.order_id == order_id), None)
        order_title = picked.title if picked else order_id
        return_result = initiate_return(
            order_id,
            incident_id=pending.incident_id,
            asin=picked.asin if picked else None,
            config=CONFIG,
        )
        return_log.append(
            {
                "incident_id": pending.incident_id,
                "decision": "ask_confirmed",
                "order_id": order_id,
                "order_title": order_title,
                "ok": return_result.ok,
                "return_id": return_result.return_id,
                "error": return_result.error,
                "dry_run": return_result.dry_run,
            }
        )
        return Response(content="<Response/>", media_type="application/xml")

    return app


app = create_app()
