"""FastAPI routes for the phone-as-third-eye flow.

Mount with::

    from phone_camera import create_phone_camera_router
    app.include_router(create_phone_camera_router())

Endpoints (all prefixed with the router's chosen path):
    GET  /pair                         desktop pairing UI with QR code
    GET  /pair/qr.png                  the QR PNG itself (handy for embedding)
    GET  /cam/{token}                  phone-side capture page
    WS   /camera/{token}/ws            phone -> server JPEG stream
    POST /camera/{token}/frame         alt HTTP fallback (raw JPEG body)
    GET  /camera/{token}/latest.jpg    most recent JPEG (cache-busted from UI)
    GET  /camera/{token}/stream.mjpg   live MJPEG stream (consumed by OpenCV)
    GET  /camera/{token}/status        JSON status of this pairing slot
    GET  /camera/status                JSON status of all known pairings
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .qr import render_qr_png
from .store import FrameStore, get_frame_store
from .templates import render_camera_page, render_pair_page

log = logging.getLogger("phone_camera.routes")


def _public_base_from_request(request: Request, override: Optional[str]) -> str:
    """Pick the URL the phone should connect to.

    Priority:
      1. Explicit override from action_router.config.public_base_url (so the
         QR points at the ngrok URL even when this hits localhost first).
      2. The request's own scheme + host (works for LAN testing).
    """
    if override:
        candidate = override.rstrip("/")
        if candidate and "127.0.0.1" not in candidate and "localhost" not in candidate:
            return candidate
    # Honor X-Forwarded-Proto / X-Forwarded-Host so ngrok-tunneled requests
    # produce the right scheme (https) and host.
    fwd_proto = request.headers.get("x-forwarded-proto")
    fwd_host = request.headers.get("x-forwarded-host")
    scheme = fwd_proto or request.url.scheme
    host = fwd_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}".rstrip("/")


def _ws_base(public_base: str) -> str:
    if public_base.startswith("https://"):
        return "wss://" + public_base[len("https://"):]
    if public_base.startswith("http://"):
        return "ws://" + public_base[len("http://"):]
    return public_base


def create_phone_camera_router(
    *,
    store: Optional[FrameStore] = None,
    public_base_url_provider=None,
) -> APIRouter:
    """Build the phone-camera router.

    `public_base_url_provider` is a zero-arg callable returning the public
    base URL string. Defaulting to a callable rather than a value lets the
    router pick up live changes (e.g. when ngrok rotates).
    """
    router = APIRouter(tags=["phone-camera"])
    frame_store = store or get_frame_store()

    def _public_base(request: Request) -> str:
        override = public_base_url_provider() if public_base_url_provider else None
        return _public_base_from_request(request, override)

    # ------------------------------------------------------------------
    # Desktop pairing UI
    # ------------------------------------------------------------------

    @router.get("/pair", response_class=HTMLResponse, include_in_schema=False)
    def pair_page(request: Request, token: Optional[str] = Query(default=None)) -> HTMLResponse:
        token = (token or frame_store.default_token).strip() or frame_store.default_token
        frame_store.ensure_slot(token)
        base = _public_base(request)
        cam_url = f"{base}/cam/{token}"
        qr_url = f"/pair/qr.png?token={token}"
        status_url = f"/camera/{token}/status"
        return HTMLResponse(
            render_pair_page(
                token=token,
                cam_url=cam_url,
                qr_url=qr_url,
                status_url=status_url,
            )
        )

    @router.get("/pair/qr.png", include_in_schema=False)
    def pair_qr(request: Request, token: Optional[str] = Query(default=None)) -> Response:
        token = (token or frame_store.default_token).strip() or frame_store.default_token
        base = _public_base(request)
        cam_url = f"{base}/cam/{token}"
        png = render_qr_png(cam_url)
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    # ------------------------------------------------------------------
    # Phone-side capture UI
    # ------------------------------------------------------------------

    @router.get("/cam/{token}", response_class=HTMLResponse, include_in_schema=False)
    def cam_page(request: Request, token: str) -> HTMLResponse:
        token = (token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="missing token")
        frame_store.ensure_slot(token)
        base = _public_base(request)
        ws_url = f"{_ws_base(base)}/camera/{token}/ws"
        return HTMLResponse(
            render_camera_page(token=token, ws_url=ws_url, label_default="My phone")
        )

    # ------------------------------------------------------------------
    # Frame ingest: WebSocket (primary) + HTTP POST (fallback)
    # ------------------------------------------------------------------

    @router.websocket("/camera/{token}/ws")
    async def camera_ws(websocket: WebSocket, token: str) -> None:
        await websocket.accept()
        label = websocket.query_params.get("label")
        slot = frame_store.ensure_slot(token, label=label)
        peer = (
            f"{websocket.client.host}:{websocket.client.port}"
            if websocket.client else "unknown"
        )
        log.info("phone-camera ws connected token=%s peer=%s label=%r", token, peer, label)
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if not data:
                    text = msg.get("text") or ""
                    if text.startswith("label:"):
                        slot.label = text[len("label:"):].strip() or slot.label
                    continue
                # Optional: enforce JPEG magic to reject random binary.
                if not data[:3] in (b"\xff\xd8\xff",):
                    continue
                frame_store.publish_frame(token, data, label=slot.label)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning("phone-camera ws error token=%s: %s", token, exc)
        finally:
            log.info(
                "phone-camera ws closed token=%s frames=%d",
                token,
                slot.frame_count,
            )

    @router.post("/camera/{token}/frame")
    async def camera_http_frame(
        request: Request,
        token: str,
        label: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="empty body")
        if body[:3] != b"\xff\xd8\xff":
            raise HTTPException(status_code=415, detail="expected JPEG body")
        slot = frame_store.publish_frame(token, body, label=label)
        return JSONResponse({"ok": True, "frame": slot.frame_count})

    # ------------------------------------------------------------------
    # Frame egress: latest JPEG, MJPEG stream, status JSON
    # ------------------------------------------------------------------

    @router.get("/camera/{token}/latest.jpg")
    def latest_jpeg(token: str) -> Response:
        slot = frame_store.get(token)
        if slot is None or slot.latest_jpeg is None:
            raise HTTPException(status_code=404, detail="no frame yet")
        return Response(
            content=slot.latest_jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @router.get("/camera/{token}/stream.mjpg")
    async def mjpeg_stream(token: str) -> StreamingResponse:
        """Multipart MJPEG stream consumed directly by `cv2.VideoCapture`."""
        boundary = "frame"
        media_type = f"multipart/x-mixed-replace; boundary={boundary}"

        async def generator():
            queue = frame_store.subscribe(token)
            try:
                while True:
                    try:
                        # Heartbeat so OpenCV's underlying ffmpeg doesn't time
                        # out before the first phone frame arrives.
                        chunk = await asyncio.wait_for(queue.get(), timeout=8.0)
                    except asyncio.TimeoutError:
                        # Re-yield the latest cached frame if any so consumers
                        # stay hot. If nothing, send a 1px sentinel.
                        slot = frame_store.get(token)
                        if slot and slot.latest_jpeg:
                            chunk = slot.latest_jpeg
                        else:
                            continue
                    while True:
                        try:
                            chunk = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    header = (
                        f"--{boundary}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(chunk)}\r\n\r\n"
                    ).encode("ascii")
                    yield header + chunk + b"\r\n"
            finally:
                frame_store.unsubscribe(token, queue)

        return StreamingResponse(generator(), media_type=media_type)

    @router.get("/camera/{token}/status")
    def slot_status(token: str) -> JSONResponse:
        slot = frame_store.get(token)
        if slot is None:
            return JSONResponse({"token": token, "connected": False, "live": False})
        return JSONResponse(slot.status())

    @router.get("/camera/status")
    def all_status() -> JSONResponse:
        return JSONResponse({"phones": frame_store.all_status()})

    return router
