"""Discovery + camera-registry routes for the action router.

The brain runs the existing vision pipeline as one or more child processes.
Each child watches a single video source (an MJPEG URL discovered via mDNS
or any URL passed in by hand). The registry below tracks those children:

  +---------------------+     POST /api/cameras/add        +-----------------+
  |  /api/discover      | --> validate URL                  | subprocess.Popen|
  |  -> mDNS browse     |     enforce cap                  | vision_engine   |
  +---------------------+     spawn with NODE_ID env       +-----------------+
                                       |                            |
                                       v                            v
                              registry[node_id] = entry      engine loads YOLO+Qwen
                                       |                            |
  GET /api/cameras  <------+ poll status (warming|running|crashed)  |
                           |     (PID alive?)                       |
                           +----------- POST /internal/camera/ready (signals run)

The cap (default 1) defends against memory pressure: each engine subprocess
loads its own copy of YOLO + Qwen2-VL (~5-6GB resident). The cap is lifted
by setting `SAFEWATCH_CAMERA_CAP=N` once you've measured headroom on the
actual demo brain laptop.

URL validation rejects anything that isn't a private-LAN HTTP/RTSP target.
The intent is twofold: (1) prevent a malicious POST from pointing the
brain at an attacker's server during a live demo, and (2) keep all media
ingest on the trusted local network so the privacy story stays honest.
"""

from __future__ import annotations

import atexit
import ipaddress
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from vision_pipeline import discovery as discovery_mod

log = logging.getLogger("action_router.discovery_routes")

DEFAULT_CAMERA_CAP = int(os.getenv("SAFEWATCH_CAMERA_CAP", "1"))
DEFAULT_DISCOVERY_TIMEOUT = float(os.getenv("SAFEWATCH_DISCOVERY_TIMEOUT", "5.0"))
ALLOWED_PORTS: set[int] = {80, 8765, 8001, 554, 8554, 8080}
ALLOWED_SCHEMES: set[str] = {"http", "rtsp"}

STATUS_WARMING = "warming"
STATUS_RUNNING = "running"
STATUS_CRASHED = "crashed"


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _is_private_host(host: str) -> bool:
    """True if `host` resolves to (or already is) a private-LAN address.

    Accepts:
      - RFC 1918 (10/8, 172.16/12, 192.168/16)
      - Loopback (127/8) — brain + sensor on the same laptop
      - Link-local (169.254/16)
      - Tailscale CGNAT (100.64/10) — common home mesh setup, real LAN-equivalent

    Hostnames that don't resolve are rejected; we only accept `.local.` mDNS
    names explicitly. We do NOT do a full DNS lookup (slow, and a hostile DNS
    could lie about what's "private").
    """
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return True
        if isinstance(ip, ipaddress.IPv4Address) and ip in _TAILSCALE_CGNAT:
            return True
        return False
    except ValueError:
        if host.endswith(".local") or host.endswith(".local."):
            return True
        return False


def validate_stream_url(raw: str) -> str:
    """Return the normalized URL or raise HTTPException(400)."""
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="stream_url is required")
    url = raw.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported scheme {parsed.scheme!r}; allowed: {sorted(ALLOWED_SCHEMES)}",
        )
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="missing host in stream_url")
    port = parsed.port or (554 if parsed.scheme == "rtsp" else 80)
    if port not in ALLOWED_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"port {port} not in allowed list {sorted(ALLOWED_PORTS)}",
        )
    if not _is_private_host(parsed.hostname):
        raise HTTPException(
            status_code=400,
            detail=(
                f"host {parsed.hostname!r} is not a private-LAN address; "
                "discovery only registers cameras on your local network"
            ),
        )
    return url


# ---------------------------------------------------------------------------
# Camera registry
# ---------------------------------------------------------------------------


@dataclass
class CameraEntry:
    node_id: str
    name: str
    stream_url: str
    pid: int
    started_at: float
    process: subprocess.Popen[bytes] | None = field(repr=False, default=None)
    status: str = STATUS_WARMING
    ready_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "stream_url": self.stream_url,
            "pid": self.pid,
            "started_at": self.started_at,
            "status": self.status,
            "ready_at": self.ready_at,
        }


class CameraRegistry:
    """Track running engine subprocesses; enforce the concurrency cap."""

    def __init__(self, *, cap: int = DEFAULT_CAMERA_CAP) -> None:
        self._cap = max(1, int(cap))
        self._entries: dict[str, CameraEntry] = {}
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def cap(self) -> int:
        return self._cap

    def active(self) -> list[CameraEntry]:
        with self._lock:
            self._refresh_locked()
            return list(self._entries.values())

    def add(self, *, name: str, stream_url: str) -> CameraEntry:
        with self._lock:
            self._refresh_locked()
            running = [e for e in self._entries.values() if e.status != STATUS_CRASHED]
            if len(running) >= self._cap:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"camera cap reached ({self._cap}); set "
                        "SAFEWATCH_CAMERA_CAP to lift after verifying RAM headroom"
                    ),
                )
            self._counter += 1
            node_id = f"cam_{self._counter:04d}_{int(time.time())}"
            proc = self._spawn_engine(node_id=node_id, stream_url=stream_url)
            entry = CameraEntry(
                node_id=node_id,
                name=name,
                stream_url=stream_url,
                pid=proc.pid,
                started_at=time.time(),
                process=proc,
            )
            self._entries[node_id] = entry
            log.info("spawned engine pid=%d node_id=%s url=%s", proc.pid, node_id, stream_url)
            return entry

    def mark_ready(self, node_id: str) -> bool:
        with self._lock:
            entry = self._entries.get(node_id)
            if entry is None:
                return False
            entry.status = STATUS_RUNNING
            entry.ready_at = time.time()
            log.info("engine ready node_id=%s after %.1fs", node_id, entry.ready_at - entry.started_at)
            return True

    def shutdown_all(self, *, timeout: float = 3.0) -> None:
        """Send SIGTERM to every tracked subprocess; wait briefly; SIGKILL stragglers."""
        with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            proc = entry.process
            if proc is None or proc.poll() is not None:
                continue
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                log.debug("SIGTERM failed for pid=%s", entry.pid, exc_info=True)
        deadline = time.monotonic() + timeout
        for entry in entries:
            proc = entry.process
            if proc is None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    log.debug("SIGKILL failed for pid=%s", entry.pid, exc_info=True)
            except Exception:
                log.debug("wait failed for pid=%s", entry.pid, exc_info=True)
        log.info("camera registry shut down (%d entries)", len(entries))

    # -- internal helpers ----------------------------------------------------

    def _refresh_locked(self) -> None:
        for entry in self._entries.values():
            if entry.status == STATUS_CRASHED:
                continue
            proc = entry.process
            if proc is None:
                continue
            rc = proc.poll()
            if rc is not None:
                entry.status = STATUS_CRASHED
                log.warning("engine pid=%d node_id=%s exited rc=%s", entry.pid, entry.node_id, rc)

    def _spawn_engine(self, *, node_id: str, stream_url: str) -> subprocess.Popen[bytes]:
        env = {
            **os.environ,
            "NODE_ID": node_id,
            "CAMERA_SOURCE": stream_url,
        }
        cmd = [sys.executable, "-m", "vision_pipeline.engine", "--source", stream_url, "--hide-window"]
        try:
            return subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"failed to spawn engine: {exc}")


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


class AddCameraRequest(BaseModel):
    stream_url: str = Field(..., description="MJPEG-over-HTTP or RTSP URL on the LAN")
    name: str = Field("camera", description="Human-readable label shown in /api/cameras")


class ReadySignal(BaseModel):
    node_id: str


def create_discovery_router(registry: CameraRegistry | None = None) -> APIRouter:
    router = APIRouter()
    reg = registry or CameraRegistry()
    # Hook atexit so child engines die when the brain dies. We also expose
    # `reg` on the router so tests can inspect/inject.
    atexit.register(reg.shutdown_all)
    router.state_registry = reg  # type: ignore[attr-defined]

    @router.get("/api/discover")
    def api_discover(request: Request) -> JSONResponse:
        # Sync def => FastAPI runs us in its threadpool, so the 5-second
        # zeroconf browse does not block the event loop.
        timeout = DEFAULT_DISCOVERY_TIMEOUT
        try:
            timeout_param = request.query_params.get("timeout")
            if timeout_param is not None:
                timeout = max(0.5, min(15.0, float(timeout_param)))
        except (TypeError, ValueError):
            pass
        cameras = discovery_mod.discover_cameras(timeout=timeout)
        return JSONResponse([c.to_dict() for c in cameras])

    @router.post("/api/cameras/add")
    def api_cameras_add(payload: AddCameraRequest) -> JSONResponse:
        url = validate_stream_url(payload.stream_url)
        entry = reg.add(name=payload.name, stream_url=url)
        return JSONResponse(entry.to_dict(), status_code=201)

    @router.get("/api/cameras")
    def api_cameras_list() -> JSONResponse:
        return JSONResponse([e.to_dict() for e in reg.active()])

    @router.post("/internal/camera/ready")
    def api_camera_ready(payload: ReadySignal) -> JSONResponse:
        ok = reg.mark_ready(payload.node_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown node_id {payload.node_id!r}")
        return JSONResponse({"ok": True})

    return router
