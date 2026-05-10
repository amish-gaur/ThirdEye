"""End-to-end tests for the phone-as-third-eye flow.

These cover the FastAPI surface only — the JS that runs on the phone is
exercised manually. We verify:
  * pair page renders with QR, capture URL, and status hooks
  * QR endpoint returns a real PNG
  * camera page renders with the right WebSocket URL
  * HTTP frame upload works (used as a fallback for environments where WS is flaky)
  * latest.jpg returns the most recent frame after ingest
  * status JSON tracks frame count, label, and connectedness
  * MJPEG stream emits a multipart frame
  * source resolver maps phone shortcuts to MJPEG URLs
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from phone_camera import create_phone_camera_router
from phone_camera.store import FrameStore
from vision_pipeline.source_resolver import resolve_camera_source


# The phone-camera ingest only validates the first three bytes (the JPEG SOI
# marker). We keep the test fixture small and dependency-free; OpenCV/PIL
# decoding is exercised by the live integration, not these unit tests.
JPEG_1PX = b"\xff\xd8\xff" + b"safewatch-phone-camera-test-frame"


@pytest.fixture
def app_and_store() -> tuple[FastAPI, FrameStore]:
    store = FrameStore()
    app = FastAPI()
    app.include_router(
        create_phone_camera_router(store=store, public_base_url_provider=lambda: "")
    )
    return app, store


@pytest.fixture
def client(app_and_store) -> TestClient:
    app, _ = app_and_store
    return TestClient(app)


# --------------------------------------------------------------------------
# Pair UI + QR
# --------------------------------------------------------------------------

def test_pair_page_renders_with_qr_and_capture_url(client: TestClient) -> None:
    resp = client.get("/pair")
    assert resp.status_code == 200
    body = resp.text
    # Must reference the capture page URL the QR will encode.
    assert "/cam/default" in body
    # Must reference the QR image endpoint.
    assert "/pair/qr.png" in body
    # Must include the status hook for the live indicator.
    assert "/camera/default/status" in body


def test_pair_page_supports_custom_token(client: TestClient) -> None:
    resp = client.get("/pair", params={"token": "porch"})
    assert resp.status_code == 200
    assert "/cam/porch" in resp.text


def test_qr_endpoint_returns_png_with_qr_magic_bytes(client: TestClient) -> None:
    resp = client.get("/pair/qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    # PNG magic number.
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Sanity: a 280x280-ish QR is at least a few hundred bytes.
    assert len(resp.content) > 200


# --------------------------------------------------------------------------
# Phone-side capture page
# --------------------------------------------------------------------------

def test_camera_page_uses_websocket_url(client: TestClient) -> None:
    resp = client.get("/cam/lobby")
    assert resp.status_code == 200
    body = resp.text
    # Should embed the per-token WS URL the JS connects to.
    assert "/camera/lobby/ws" in body
    assert "ws://" in body or "wss://" in body
    # And reference the token in the page state.
    assert ">lobby<" in body


# --------------------------------------------------------------------------
# Frame ingest (HTTP fallback) + latest.jpg + status
# --------------------------------------------------------------------------

def test_latest_jpeg_404_before_any_frame(client: TestClient) -> None:
    resp = client.get("/camera/default/latest.jpg")
    assert resp.status_code == 404


def test_status_for_unconnected_token(client: TestClient) -> None:
    resp = client.get("/camera/never-paired/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["live"] is False


def test_http_frame_upload_publishes_and_serves_latest(
    client: TestClient, app_and_store
) -> None:
    _, store = app_and_store
    resp = client.post(
        "/camera/default/frame",
        content=JPEG_1PX,
        headers={"content-type": "image/jpeg"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # latest.jpg now returns exactly the bytes we uploaded.
    latest = client.get("/camera/default/latest.jpg")
    assert latest.status_code == 200
    assert latest.headers["content-type"] == "image/jpeg"
    assert latest.content == JPEG_1PX

    # Status flips to connected + live.
    status = client.get("/camera/default/status").json()
    assert status["connected"] is True
    assert status["live"] is True
    assert status["frame_count"] == 1

    slot = store.get("default")
    assert slot is not None
    assert slot.latest_jpeg == JPEG_1PX


def test_http_frame_upload_rejects_non_jpeg(client: TestClient) -> None:
    resp = client.post(
        "/camera/default/frame",
        content=b"not a jpeg",
        headers={"content-type": "image/jpeg"},
    )
    assert resp.status_code == 415


def test_status_endpoint_lists_all_phones(client: TestClient) -> None:
    client.post(
        "/camera/lobby/frame",
        content=JPEG_1PX,
        headers={"content-type": "image/jpeg"},
    )
    body = client.get("/camera/status").json()
    tokens = {p["token"] for p in body["phones"]}
    assert {"default", "lobby"}.issubset(tokens)


# --------------------------------------------------------------------------
# MJPEG egress (sync part: headers + first chunk)
# --------------------------------------------------------------------------

def test_mjpeg_stream_endpoint_exists_with_correct_content_type(
    client: TestClient, app_and_store
) -> None:
    """We verify headers + that the generator emits a primed multipart frame.

    We can't drain the live MJPEG stream from the sync TestClient (it never
    EOFs by design). Instead we exercise the response factory and the first
    chunk of the underlying async generator directly — that's where all the
    interesting code is.
    """
    from phone_camera.routes import create_phone_camera_router

    _, store = app_and_store
    store.publish_frame("default", JPEG_1PX)

    # Pull the underlying async generator out of the route and pull one chunk
    # so we can assert the multipart framing is correct.
    router = create_phone_camera_router(store=store, public_base_url_provider=lambda: "")
    mjpeg_route = next(
        r for r in router.routes if getattr(r, "path", "") == "/camera/{token}/stream.mjpg"
    )
    response = asyncio.run(mjpeg_route.endpoint(token="default"))
    assert "multipart/x-mixed-replace" in response.media_type

    async def _first_chunk():
        async for chunk in response.body_iterator:
            return chunk
        return b""

    chunk = asyncio.run(_first_chunk())
    assert b"--frame" in chunk
    assert b"Content-Type: image/jpeg" in chunk
    assert JPEG_1PX in chunk


# --------------------------------------------------------------------------
# Frame store unit tests
# --------------------------------------------------------------------------

def test_frame_store_subscribers_receive_new_frames() -> None:
    async def _run():
        store = FrameStore()
        q = store.subscribe("default")
        store.publish_frame("default", JPEG_1PX)
        chunk = await asyncio.wait_for(q.get(), timeout=1.0)
        assert chunk == JPEG_1PX

    asyncio.run(_run())


def test_frame_store_primes_subscribers_with_latest() -> None:
    async def _run():
        store = FrameStore()
        store.publish_frame("default", JPEG_1PX)
        q = store.subscribe("default")
        chunk = await asyncio.wait_for(q.get(), timeout=1.0)
        assert chunk == JPEG_1PX

    asyncio.run(_run())


# --------------------------------------------------------------------------
# Source resolver
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0", 0),
        ("", 0),
        ("rtsp://camera.local/stream", "rtsp://camera.local/stream"),
        ("phone", "http://127.0.0.1:8001/camera/default/stream.mjpg"),
        ("PHONE", "http://127.0.0.1:8001/camera/default/stream.mjpg"),
        ("phone:lobby", "http://127.0.0.1:8001/camera/lobby/stream.mjpg"),
        ("phone://lobby", "http://127.0.0.1:8001/camera/lobby/stream.mjpg"),
        (
            "phone://192.168.1.20:8001/lobby",
            "http://192.168.1.20:8001/camera/lobby/stream.mjpg",
        ),
        (
            "phone://https://router.ngrok.app/lobby",
            "https://router.ngrok.app/camera/lobby/stream.mjpg",
        ),
    ],
)
def test_source_resolver_maps_shortcuts(raw, expected) -> None:
    assert resolve_camera_source(raw, default_base="http://127.0.0.1:8001") == expected


def test_source_resolver_honors_default_base_override() -> None:
    out = resolve_camera_source(
        "phone:lobby", default_base="http://10.0.0.5:8001"
    )
    assert out == "http://10.0.0.5:8001/camera/lobby/stream.mjpg"
