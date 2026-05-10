"""SafeWatch sensor: turn this laptop's webcam into a discoverable camera.

The brain (action_router) finds us via mDNS (`_safewatch._tcp.local.`) and
consumes our MJPEG stream over plain HTTP. We deliberately do NOT use RTSP:
the existing vision engine consumes MJPEG over HTTP through
`source_resolver.resolve_camera_source` for the phone-camera flow, so this
sensor reuses the same ingest path with zero binary dependencies.

Lifecycle:
    1. Open `cv2.VideoCapture(device_index)` lazily on the first stream
       request. Holding the device open before anyone connects would block
       FaceTime / Zoom / other apps on the same laptop.
    2. Register a `_safewatch._tcp` Zeroconf service announcing our HTTP
       port + the stream path.
    3. On SIGINT / SIGTERM / atexit, unregister the service and release the
       capture so the second `python -m safewatch_sensor` doesn't fail with
       "device busy."

Usage:
    python -m safewatch_sensor                    # default port 8765, device 0
    SAFEWATCH_SENSOR_PORT=9000 python -m safewatch_sensor
    SAFEWATCH_SENSOR_DEVICE=1 python -m safewatch_sensor
    SAFEWATCH_SENSOR_NAME="Rishab MBP" python -m safewatch_sensor
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import signal
import socket
import sys
import threading
import time
from typing import Iterable

import cv2
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from zeroconf import IPVersion, ServiceInfo, Zeroconf

log = logging.getLogger("safewatch_sensor")

DEFAULT_PORT = 8765
SERVICE_TYPE = "_safewatch._tcp.local."
STREAM_PATH = "/stream.mjpg"
JPEG_QUALITY = 70
TARGET_FPS = 15  # capped — judges' laptops vary, the brain's YOLO runs at 10fps anyway


# ---------------------------------------------------------------------------
# Webcam -> MJPEG generator
# ---------------------------------------------------------------------------


class _Webcam:
    """Lazy, reference-counted webcam handle.

    Multiple HTTP clients can connect simultaneously (the brain plus a
    debug VLC window, say). We open VideoCapture on first connect, keep it
    open while clients are connected, and release it cleanly when the last
    one disconnects. This matters because macOS keeps the green camera
    light on while VideoCapture is open — releasing properly is good
    citizenship and fixes "device busy" on rapid restart.
    """

    def __init__(self, device: int) -> None:
        self._device = device
        self._cap: cv2.VideoCapture | None = None
        self._refcount = 0
        self._lock = threading.Lock()

    def acquire(self) -> cv2.VideoCapture:
        with self._lock:
            if self._cap is None:
                cap = cv2.VideoCapture(self._device)
                if not cap.isOpened():
                    raise RuntimeError(
                        f"failed to open webcam device {self._device}"
                    )
                self._cap = cap
            self._refcount += 1
            return self._cap

    def release(self) -> None:
        with self._lock:
            self._refcount = max(0, self._refcount - 1)
            if self._refcount == 0 and self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    log.debug("VideoCapture release failed", exc_info=True)
                self._cap = None

    def force_release(self) -> None:
        """Used during shutdown — drop the device regardless of refcount."""
        with self._lock:
            self._refcount = 0
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    log.debug("VideoCapture force release failed", exc_info=True)
                self._cap = None


def _mjpeg_frames(webcam: _Webcam, fps: int) -> Iterable[bytes]:
    """Yield multipart MJPEG frames forever (until the client disconnects)."""
    cap = webcam.acquire()
    boundary = b"--frame\r\n"
    interval = 1.0 / max(1, fps)
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
    try:
        while True:
            t0 = time.monotonic()
            ok, frame = cap.read()
            if not ok or frame is None:
                # Camera dropped a frame — wait briefly and retry rather
                # than tearing down the whole stream.
                time.sleep(0.05)
                continue
            ok, jpg = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue
            payload = jpg.tobytes()
            yield (
                boundary
                + b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                + payload
                + b"\r\n"
            )
            elapsed = time.monotonic() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)
    finally:
        webcam.release()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


def build_app(webcam: _Webcam, *, sensor_name: str, fps: int = TARGET_FPS) -> FastAPI:
    app = FastAPI(title="SafeWatch Sensor", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True, "name": sensor_name})

    @app.get(STREAM_PATH)
    def stream() -> StreamingResponse:
        return StreamingResponse(
            _mjpeg_frames(webcam, fps=fps),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app


# ---------------------------------------------------------------------------
# Zeroconf advertise
# ---------------------------------------------------------------------------


def _local_ip() -> str:
    """Best-effort: figure out which IP other LAN hosts will reach us on."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # We don't actually send a packet — connect() just picks a route.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def register_service(
    zc: Zeroconf, *, sensor_name: str, port: int, host_ip: str | None = None
) -> ServiceInfo:
    ip = host_ip or _local_ip()
    safe_name = sensor_name.replace(".", "_")
    full_name = f"{safe_name}.{SERVICE_TYPE}"
    info = ServiceInfo(
        type_=SERVICE_TYPE,
        name=full_name,
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={
            "name": sensor_name,
            "path": STREAM_PATH,
            "kind": "webcam",
        },
        server=f"{safe_name}.local.",
    )
    zc.register_service(info)
    log.info("registered mDNS service %s at %s:%d", full_name, ip, port)
    return info


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _default_sensor_name() -> str:
    raw = os.getenv("SAFEWATCH_SENSOR_NAME")
    if raw:
        return raw
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "safewatch-sensor"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="safewatch_sensor",
        description="Turn this laptop's webcam into a SafeWatch-discoverable sensor.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("SAFEWATCH_SENSOR_PORT", str(DEFAULT_PORT))),
    )
    parser.add_argument(
        "--device",
        type=int,
        default=int(os.getenv("SAFEWATCH_SENSOR_DEVICE", "0")),
    )
    parser.add_argument(
        "--name",
        default=_default_sensor_name(),
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=int(os.getenv("SAFEWATCH_SENSOR_FPS", str(TARGET_FPS))),
    )
    parser.add_argument(
        "--no-announce",
        action="store_true",
        help="Run the HTTP server but skip mDNS announce (useful for tests).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    args = parse_args(argv)

    webcam = _Webcam(device=args.device)
    app = build_app(webcam, sensor_name=args.name, fps=args.fps)

    zc: Zeroconf | None = None
    info: ServiceInfo | None = None
    if not args.no_announce:
        zc = Zeroconf(ip_version=IPVersion.V4Only)
        info = register_service(zc, sensor_name=args.name, port=args.port)

    cleaned_up = threading.Event()

    def _cleanup(*_a: object) -> None:
        if cleaned_up.is_set():
            return
        cleaned_up.set()
        log.info("shutting down sensor")
        try:
            if zc is not None and info is not None:
                zc.unregister_service(info)
        except Exception:
            log.debug("unregister_service failed", exc_info=True)
        try:
            if zc is not None:
                zc.close()
        except Exception:
            log.debug("zeroconf close failed", exc_info=True)
        webcam.force_release()

    atexit.register(_cleanup)
    # Hook SIGINT/SIGTERM so cleanup runs even when uvicorn handles the
    # signal first (uvicorn calls sys.exit which fires atexit anyway, but
    # we double-wire to be defensive).
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: _cleanup() or sys.exit(0))
        except (ValueError, OSError):
            # Not main thread on some platforms — atexit alone has us covered.
            pass

    log.info(
        "starting sensor name=%r port=%d device=%d fps=%d announce=%s",
        args.name,
        args.port,
        args.device,
        args.fps,
        not args.no_announce,
    )
    try:
        uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
    finally:
        _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
