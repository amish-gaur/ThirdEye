"""LAN camera discovery via mDNS / Zeroconf.

The brain calls `discover_cameras(timeout=5.0)` and gets back a list of
cameras advertising themselves on the local network. For SafeWatch's V1,
the only protocol we browse is `_safewatch._tcp.local.` — published by
the `safewatch_sensor` daemon running on each demo laptop.

Each sensor announces an MJPEG-over-HTTP stream URL (not RTSP) because the
existing vision engine already consumes MJPEG via OpenCV's VideoCapture
(see `vision_pipeline/source_resolver.py`). Reusing that path means zero
binary vendoring (no mediamtx) and zero new ingest plumbing.

Discovery is intentionally synchronous-with-deadline rather than async:
FastAPI runs sync `def` handlers in its threadpool, so a 5-second blocking
browse does not stall the event loop. Keeping this module sync makes it
trivially unit-testable too — no event-loop fixtures required.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

log = logging.getLogger("vision_pipeline.discovery")

SERVICE_TYPE = "_safewatch._tcp.local."
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class DiscoveredCamera:
    name: str
    host: str
    port: int
    stream_url: str
    source_protocol: str  # "mdns" today; future: "onvif", "rtsp-probe"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Collector(ServiceListener):
    """Stash service-info entries by full service name; dedupe naturally."""

    def __init__(self) -> None:
        self._services: dict[str, DiscoveredCamera] = {}

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._services.pop(name, None)

    def _record(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=1500)
        if info is None or not info.addresses:
            return
        host = socket.inet_ntoa(info.addresses[0])
        port = int(info.port or 0)
        if port <= 0:
            return
        # Properties are bytes -> bytes. Decode permissively.
        props = {
            k.decode("utf-8", "replace"): (v.decode("utf-8", "replace") if v else "")
            for k, v in (info.properties or {}).items()
        }
        path = props.get("path", "/stream.mjpg").lstrip("/")
        display_name = props.get("name") or name.split(".")[0] or host
        stream_url = f"http://{host}:{port}/{path}"
        self._services[name] = DiscoveredCamera(
            name=display_name,
            host=host,
            port=port,
            stream_url=stream_url,
            source_protocol="mdns",
        )

    def snapshot(self) -> list[DiscoveredCamera]:
        return list(self._services.values())


def discover_cameras(
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    *,
    zeroconf: Zeroconf | None = None,
) -> list[DiscoveredCamera]:
    """Browse the LAN for SafeWatch sensors. Blocks for up to `timeout`s.

    Returns a deduped list of DiscoveredCamera. Empty list on no results or
    if multicast is blocked on the network (common on hostile WiFi). Callers
    should treat empty as "nothing found," never as an error.
    """
    timeout = max(0.5, float(timeout))
    own_zc = zeroconf is None
    zc = zeroconf or Zeroconf()
    collector = _Collector()
    browser = ServiceBrowser(zc, SERVICE_TYPE, collector)
    try:
        time.sleep(timeout)
        return collector.snapshot()
    finally:
        try:
            browser.cancel()
        except Exception:
            log.debug("ServiceBrowser cancel failed", exc_info=True)
        if own_zc:
            try:
                zc.close()
            except Exception:
                log.debug("Zeroconf close failed", exc_info=True)
