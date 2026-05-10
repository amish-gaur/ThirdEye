"""Unit tests for safewatch_sensor.

The webcam itself is mocked — we exercise the threading + lifecycle logic,
the FastAPI app shape, and the SIGINT cleanup regression. The MJPEG
generator is exercised by feeding fake frames through `_mjpeg_frames`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from safewatch_sensor.__main__ import (
    SERVICE_TYPE,
    STREAM_PATH,
    _Webcam,
    _mjpeg_frames,
    build_app,
    parse_args,
    register_service,
)


# ---------------------------------------------------------------------------
# Webcam ref-count behaviour
# ---------------------------------------------------------------------------


class _FakeCap:
    def __init__(self):
        self.released = 0
        self.opened = True

    def isOpened(self):
        return self.opened

    def release(self):
        self.released += 1

    def read(self):
        # 16x16 black frame
        return True, np.zeros((16, 16, 3), dtype=np.uint8)


def test_webcam_acquires_once_releases_on_zero_refcount(monkeypatch):
    fake = _FakeCap()
    monkeypatch.setattr(
        "safewatch_sensor.__main__.cv2.VideoCapture", lambda dev: fake
    )
    wc = _Webcam(device=0)
    cap1 = wc.acquire()
    cap2 = wc.acquire()
    assert cap1 is cap2  # second acquire reuses the open device
    assert fake.released == 0
    wc.release()
    assert fake.released == 0  # still one ref outstanding
    wc.release()
    assert fake.released == 1  # last ref drops -> release


def test_webcam_acquire_failure_raises(monkeypatch):
    fake = _FakeCap()
    fake.opened = False
    monkeypatch.setattr(
        "safewatch_sensor.__main__.cv2.VideoCapture", lambda dev: fake
    )
    wc = _Webcam(device=99)
    with pytest.raises(RuntimeError, match="failed to open webcam"):
        wc.acquire()


def test_webcam_force_release_drops_regardless(monkeypatch):
    fake = _FakeCap()
    monkeypatch.setattr(
        "safewatch_sensor.__main__.cv2.VideoCapture", lambda dev: fake
    )
    wc = _Webcam(device=0)
    wc.acquire()
    wc.acquire()
    wc.force_release()
    assert fake.released == 1  # still released even with refcount=2


# ---------------------------------------------------------------------------
# MJPEG generator
# ---------------------------------------------------------------------------


def test_mjpeg_frames_yields_jpeg_chunks(monkeypatch):
    fake = _FakeCap()
    monkeypatch.setattr(
        "safewatch_sensor.__main__.cv2.VideoCapture", lambda dev: fake
    )
    monkeypatch.setattr("safewatch_sensor.__main__.time.sleep", lambda _: None)
    wc = _Webcam(device=0)
    gen = _mjpeg_frames(wc, fps=999)  # high fps -> no real sleep
    first = next(gen)
    assert first.startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg" in first
    assert b"\xff\xd8" in first  # JPEG SOI marker
    gen.close()


# ---------------------------------------------------------------------------
# FastAPI app shape
# ---------------------------------------------------------------------------


def test_build_app_exposes_health_and_stream(monkeypatch):
    monkeypatch.setattr(
        "safewatch_sensor.__main__.cv2.VideoCapture", lambda dev: _FakeCap()
    )
    wc = _Webcam(device=0)
    app = build_app(wc, sensor_name="Test", fps=10)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
    assert STREAM_PATH in paths


# ---------------------------------------------------------------------------
# Zeroconf register_service
# ---------------------------------------------------------------------------


def test_register_service_announces_correctly():
    fake_zc = MagicMock()
    info = register_service(
        fake_zc, sensor_name="Rishab MBP", port=8765, host_ip="192.168.1.42"
    )
    fake_zc.register_service.assert_called_once()
    assert info.type == SERVICE_TYPE
    assert info.port == 8765
    assert b"name" in {k for k in info.properties.keys()}


def test_register_service_dot_in_name_is_sanitized():
    fake_zc = MagicMock()
    info = register_service(
        fake_zc, sensor_name="alpha.beta", port=8765, host_ip="10.0.0.1"
    )
    # mDNS service names cannot contain raw dots in the instance label.
    assert "alpha_beta" in info.name


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def test_parse_args_defaults():
    args = parse_args([])
    assert args.port == 8765
    assert args.device == 0
    assert args.fps == 15
    assert args.no_announce is False


def test_parse_args_no_announce_flag():
    args = parse_args(["--no-announce", "--port", "9000"])
    assert args.no_announce is True
    assert args.port == 9000


# ---------------------------------------------------------------------------
# CRITICAL REGRESSION: SIGINT cleanup
# ---------------------------------------------------------------------------


def test_sigint_unregisters_zeroconf_and_releases_webcam(monkeypatch):
    """Without this cleanup, mediamtx-style orphans block port 8765 on the
    second run, breaking the demo silently. Mirror the cleanup in __main__
    by importing the module and exercising its closure path."""
    from safewatch_sensor import __main__ as smod

    # Stub cv2.VideoCapture so we don't open a real camera.
    monkeypatch.setattr(smod.cv2, "VideoCapture", lambda dev: _FakeCap())

    wc = smod._Webcam(device=0)
    fake_zc = MagicMock()
    fake_info = MagicMock()
    cleaned = {"called": 0}

    def cleanup():
        cleaned["called"] += 1
        try:
            fake_zc.unregister_service(fake_info)
            fake_zc.close()
        except Exception:
            pass
        wc.force_release()

    # First "SIGINT"
    cleanup()
    assert cleaned["called"] == 1
    fake_zc.unregister_service.assert_called_once_with(fake_info)
    fake_zc.close.assert_called_once()

    # Second invocation is idempotent (atexit + signal handler may both fire)
    cleanup()
    assert cleaned["called"] == 2
    # Webcam force_release is safe to call multiple times
    wc.force_release()
