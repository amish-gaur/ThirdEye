"""Endpoint + registry tests for action_router/discovery_routes.py.

We don't actually spawn vision_engine subprocesses (each loads ~6GB of
ML models). Instead we monkeypatch `CameraRegistry._spawn_engine` to
return a fake process. This isolates the route + validation + state
machine logic, which is what the design's correctness rests on.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from action_router import discovery_routes as dr
from action_router.discovery_routes import (
    CameraEntry,
    CameraRegistry,
    STATUS_CRASHED,
    STATUS_RUNNING,
    STATUS_WARMING,
    create_discovery_router,
    validate_stream_url,
)


# ---------------------------------------------------------------------------
# Fake subprocess
# ---------------------------------------------------------------------------


class FakeProc:
    def __init__(self, pid: int = 9999):
        self.pid = pid
        self._rc: int | None = None
        self.signals_received: list[int] = []

    def poll(self):
        return self._rc

    def send_signal(self, sig):
        self.signals_received.append(sig)
        self._rc = -sig

    def wait(self, timeout=None):
        return self._rc if self._rc is not None else 0

    def kill(self):
        self._rc = -9


@pytest.fixture
def fake_registry(monkeypatch):
    reg = CameraRegistry(cap=2)
    procs: list[FakeProc] = []

    def fake_spawn(self, *, node_id, stream_url):
        p = FakeProc(pid=10000 + len(procs))
        procs.append(p)
        return p

    monkeypatch.setattr(CameraRegistry, "_spawn_engine", fake_spawn)
    return reg, procs


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def test_validate_stream_url_accepts_rfc1918():
    assert (
        validate_stream_url("http://192.168.1.42:8765/stream.mjpg")
        == "http://192.168.1.42:8765/stream.mjpg"
    )
    assert validate_stream_url("http://10.0.0.5:8765/x") == "http://10.0.0.5:8765/x"
    assert validate_stream_url("http://172.16.0.1:8765/x") == "http://172.16.0.1:8765/x"


def test_validate_stream_url_accepts_loopback_and_local():
    assert validate_stream_url("http://127.0.0.1:8765/stream.mjpg")
    assert validate_stream_url("http://laptop.local:8765/stream.mjpg")


def test_validate_stream_url_accepts_tailscale_cgnat():
    """Tailscale uses 100.64.0.0/10 (CGNAT). Real home meshes show up here,
    not in RFC 1918. Surfaced by live end-to-end test."""
    assert validate_stream_url("http://100.127.176.135:8765/stream.mjpg")
    assert validate_stream_url("http://100.64.0.1:8765/stream.mjpg")


def test_validate_stream_url_accepts_rtsp():
    assert (
        validate_stream_url("rtsp://192.168.1.50:554/cam")
        == "rtsp://192.168.1.50:554/cam"
    )


def test_validate_stream_url_rejects_public_ip():
    with pytest.raises(Exception) as exc:
        validate_stream_url("http://1.1.1.1:8765/stream.mjpg")
    assert "private-LAN" in str(exc.value.detail)


def test_validate_stream_url_rejects_unknown_hostname():
    with pytest.raises(Exception):
        validate_stream_url("http://example.com:8765/stream.mjpg")


def test_validate_stream_url_rejects_bad_scheme():
    with pytest.raises(Exception) as exc:
        validate_stream_url("ftp://192.168.1.1/x")
    assert "scheme" in str(exc.value.detail)


def test_validate_stream_url_rejects_bad_port():
    with pytest.raises(Exception) as exc:
        validate_stream_url("http://192.168.1.1:31337/x")
    assert "port" in str(exc.value.detail)


def test_validate_stream_url_rejects_empty():
    with pytest.raises(Exception):
        validate_stream_url("")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_add_returns_warming_entry(fake_registry):
    reg, _ = fake_registry
    entry = reg.add(name="A", stream_url="http://192.168.1.1:8765/stream.mjpg")
    assert entry.status == STATUS_WARMING
    assert entry.pid == 10000
    assert reg.active() == [entry]


def test_registry_enforces_cap(fake_registry):
    reg, _ = fake_registry
    reg._cap = 1
    reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    with pytest.raises(Exception) as exc:
        reg.add(name="B", stream_url="http://192.168.1.2:8765/x")
    assert exc.value.status_code == 409


def test_registry_mark_ready_flips_status(fake_registry):
    reg, _ = fake_registry
    e = reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    assert reg.mark_ready(e.node_id) is True
    assert reg.active()[0].status == STATUS_RUNNING


def test_registry_mark_ready_unknown_node_returns_false(fake_registry):
    reg, _ = fake_registry
    assert reg.mark_ready("does-not-exist") is False


def test_registry_detects_crashed_subprocess(fake_registry):
    reg, procs = fake_registry
    e = reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    procs[0]._rc = 1  # simulate crash
    snap = reg.active()
    assert snap[0].status == STATUS_CRASHED


def test_registry_crashed_does_not_count_against_cap(fake_registry):
    reg, procs = fake_registry
    reg._cap = 1
    reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    procs[0]._rc = 1  # crashed
    # Cap should now allow another add
    e2 = reg.add(name="B", stream_url="http://192.168.1.2:8765/x")
    assert e2.status == STATUS_WARMING


# ---------------------------------------------------------------------------
# CRITICAL REGRESSION: atexit-style shutdown_all
# ---------------------------------------------------------------------------


def test_shutdown_all_sigterms_every_child(fake_registry):
    """Without this, brain crash leaves vision_engine subprocesses orphaned
    holding the webcam open. Demo dies on next launch."""
    reg, procs = fake_registry
    reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    reg._cap = 99
    reg.add(name="B", stream_url="http://192.168.1.2:8765/x")
    reg.shutdown_all(timeout=0.05)
    import signal
    for p in procs:
        assert signal.SIGTERM in p.signals_received


def test_shutdown_all_skips_already_dead(fake_registry):
    reg, procs = fake_registry
    reg.add(name="A", stream_url="http://192.168.1.1:8765/x")
    procs[0]._rc = 0  # already exited cleanly
    reg.shutdown_all(timeout=0.05)
    # No new signal should have been sent to a dead process
    import signal
    assert signal.SIGTERM not in procs[0].signals_received


# ---------------------------------------------------------------------------
# FastAPI route integration
# ---------------------------------------------------------------------------


def _make_app(registry: CameraRegistry) -> TestClient:
    app = FastAPI()
    app.include_router(create_discovery_router(registry))
    return TestClient(app)


def test_post_cameras_add_success(monkeypatch, fake_registry):
    reg, _ = fake_registry
    client = _make_app(reg)
    r = client.post(
        "/api/cameras/add",
        json={"stream_url": "http://192.168.1.1:8765/stream.mjpg", "name": "MBP"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == STATUS_WARMING
    assert body["name"] == "MBP"


def test_post_cameras_add_rejects_off_lan_url(monkeypatch, fake_registry):
    reg, _ = fake_registry
    client = _make_app(reg)
    r = client.post(
        "/api/cameras/add",
        json={"stream_url": "http://1.1.1.1:8765/x", "name": "evil"},
    )
    assert r.status_code == 400
    assert "private-LAN" in r.json()["detail"]


def test_post_cameras_add_returns_409_when_cap_reached(fake_registry):
    reg, _ = fake_registry
    reg._cap = 1
    client = _make_app(reg)
    client.post(
        "/api/cameras/add",
        json={"stream_url": "http://192.168.1.1:8765/x", "name": "A"},
    )
    r = client.post(
        "/api/cameras/add",
        json={"stream_url": "http://192.168.1.2:8765/x", "name": "B"},
    )
    assert r.status_code == 409


def test_get_cameras_returns_active_list(fake_registry):
    reg, _ = fake_registry
    client = _make_app(reg)
    client.post(
        "/api/cameras/add",
        json={"stream_url": "http://192.168.1.1:8765/x", "name": "A"},
    )
    r = client.get("/api/cameras")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "A"


def test_post_internal_camera_ready_flips_status(fake_registry):
    reg, _ = fake_registry
    client = _make_app(reg)
    add_resp = client.post(
        "/api/cameras/add",
        json={"stream_url": "http://192.168.1.1:8765/x", "name": "A"},
    )
    node_id = add_resp.json()["node_id"]
    r = client.post("/internal/camera/ready", json={"node_id": node_id})
    assert r.status_code == 200
    list_resp = client.get("/api/cameras").json()
    assert list_resp[0]["status"] == STATUS_RUNNING


def test_post_internal_camera_ready_unknown_node_returns_404(fake_registry):
    reg, _ = fake_registry
    client = _make_app(reg)
    r = client.post("/internal/camera/ready", json={"node_id": "ghost"})
    assert r.status_code == 404


def test_get_discover_returns_list(monkeypatch, fake_registry):
    """`/api/discover` should return a JSON array; uses the discovery module."""
    reg, _ = fake_registry
    fake_cam = MagicMock()
    fake_cam.to_dict.return_value = {"name": "X", "host": "10.0.0.1"}
    monkeypatch.setattr(
        dr.discovery_mod,
        "discover_cameras",
        lambda timeout=5.0: [fake_cam],
    )
    client = _make_app(reg)
    r = client.get("/api/discover?timeout=0.5")
    assert r.status_code == 200
    assert r.json() == [{"name": "X", "host": "10.0.0.1"}]
