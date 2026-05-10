"""Unit tests for vision_pipeline/discovery.py.

We don't spin up real Zeroconf — that needs multicast and can't run in CI.
Instead we drive the `_Collector.add_service` callback directly with a
stubbed Zeroconf that returns canned ServiceInfo.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock

import pytest

from vision_pipeline import discovery as discovery_mod
from vision_pipeline.discovery import (
    DiscoveredCamera,
    SERVICE_TYPE,
    _Collector,
    discover_cameras,
)


def _fake_service_info(*, host: str, port: int, props: dict[str, str]) -> MagicMock:
    info = MagicMock()
    info.addresses = [socket.inet_aton(host)]
    info.port = port
    info.properties = {k.encode(): v.encode() for k, v in props.items()}
    return info


def test_collector_records_service():
    zc = MagicMock()
    zc.get_service_info.return_value = _fake_service_info(
        host="192.168.1.42",
        port=8765,
        props={"name": "Rishab MBP", "path": "/stream.mjpg"},
    )
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "RishabMBP._safewatch._tcp.local.")
    snap = c.snapshot()
    assert len(snap) == 1
    cam = snap[0]
    assert cam == DiscoveredCamera(
        name="Rishab MBP",
        host="192.168.1.42",
        port=8765,
        stream_url="http://192.168.1.42:8765/stream.mjpg",
        source_protocol="mdns",
    )


def test_collector_dedupes_duplicate_announces():
    zc = MagicMock()
    zc.get_service_info.return_value = _fake_service_info(
        host="192.168.1.42", port=8765, props={"name": "A"}
    )
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "same.name.")
    c.add_service(zc, SERVICE_TYPE, "same.name.")
    c.update_service(zc, SERVICE_TYPE, "same.name.")
    assert len(c.snapshot()) == 1


def test_collector_filters_missing_info():
    zc = MagicMock()
    zc.get_service_info.return_value = None
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "ghost.local.")
    assert c.snapshot() == []


def test_collector_filters_zero_port():
    zc = MagicMock()
    zc.get_service_info.return_value = _fake_service_info(
        host="192.168.1.42", port=0, props={"name": "Bad"}
    )
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "bad.local.")
    assert c.snapshot() == []


def test_collector_falls_back_when_name_property_missing():
    zc = MagicMock()
    zc.get_service_info.return_value = _fake_service_info(
        host="10.0.0.5", port=8765, props={}  # no "name"
    )
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "anonymous._safewatch._tcp.local.")
    snap = c.snapshot()
    assert len(snap) == 1
    assert snap[0].name == "anonymous"
    assert snap[0].host == "10.0.0.5"


def test_collector_remove_service_clears():
    zc = MagicMock()
    zc.get_service_info.return_value = _fake_service_info(
        host="192.168.1.42", port=8765, props={"name": "Bye"}
    )
    c = _Collector()
    c.add_service(zc, SERVICE_TYPE, "going.local.")
    assert len(c.snapshot()) == 1
    c.remove_service(zc, SERVICE_TYPE, "going.local.")
    assert c.snapshot() == []


def test_discover_cameras_timeout_returns_empty(monkeypatch):
    """No services on the network -> empty list, never an exception."""
    fake_zc = MagicMock()
    fake_browser = MagicMock()
    monkeypatch.setattr(discovery_mod, "Zeroconf", lambda *a, **kw: fake_zc)
    monkeypatch.setattr(discovery_mod, "ServiceBrowser", lambda zc, t, l: fake_browser)
    # Skip the real sleep — test runs fast.
    monkeypatch.setattr(discovery_mod.time, "sleep", lambda _: None)
    out = discover_cameras(timeout=0.5)
    assert out == []
    fake_browser.cancel.assert_called_once()
    fake_zc.close.assert_called_once()


def test_discover_cameras_clamps_low_timeout(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(discovery_mod, "Zeroconf", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(
        discovery_mod, "ServiceBrowser", lambda *a, **kw: MagicMock()
    )
    monkeypatch.setattr(discovery_mod.time, "sleep", lambda x: sleeps.append(x))
    discover_cameras(timeout=0.0)
    assert sleeps == [0.5]
