"""Integration smoke test: real `safewatch_sensor` + real Zeroconf browse.

Run manually:
    pytest tests/test_lan_discovery_e2e.py -m integration --no-header

These tests are excluded from the default pytest run because they
(a) bind a real TCP port and require working multicast on lo0,
(b) take several seconds to converge mDNS,
(c) need `--no-announce` flag is NOT used so we exercise the real
    Zeroconf round trip.

If multicast is blocked on the dev machine (some VPNs, corp WiFi),
these tests fail without a code regression. Skip them in that case.
"""

from __future__ import annotations

import threading
import time

import pytest

pytestmark = pytest.mark.integration


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def running_sensor():
    """Spin up a sensor on localhost. Tear it down at end of test."""
    import uvicorn
    from unittest.mock import patch
    import numpy as np

    from safewatch_sensor.__main__ import _Webcam, build_app, register_service
    from zeroconf import IPVersion, Zeroconf

    class _StubCap:
        def isOpened(self):
            return True
        def read(self):
            return True, np.zeros((16, 16, 3), dtype=np.uint8)
        def release(self):
            pass

    port = _free_port()
    sensor_name = f"E2ESensor{port}"

    with patch("safewatch_sensor.__main__.cv2.VideoCapture", lambda d: _StubCap()):
        webcam = _Webcam(device=0)
        app = build_app(webcam, sensor_name=sensor_name, fps=5)

        zc = Zeroconf(ip_version=IPVersion.V4Only)
        info = register_service(
            zc, sensor_name=sensor_name, port=port, host_ip="127.0.0.1"
        )

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for the server to actually be listening.
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.1)

        try:
            yield {"name": sensor_name, "port": port}
        finally:
            server.should_exit = True
            zc.unregister_service(info)
            zc.close()
            thread.join(timeout=3)
            webcam.force_release()


def test_discover_finds_running_sensor(running_sensor):
    """Real mDNS round trip. If this fails, multicast is broken locally."""
    from vision_pipeline.discovery import discover_cameras

    found = discover_cameras(timeout=4.0)
    names = {c.name for c in found}
    assert running_sensor["name"] in names, (
        f"sensor {running_sensor['name']} not in discovered set {names}"
    )
