from fastapi.testclient import TestClient

from action_router.service import create_app
from scripts._fixtures import sample_event


def test_health_endpoint_returns_status() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "dry_run" in body


def test_event_endpoint_routes_dry_run_event() -> None:
    client = TestClient(create_app())
    payload = sample_event(tier=2)
    resp = client.post("/event", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == 2
    assert body["tier_label"] == "NOTICE"


def test_event_endpoint_rejects_non_object() -> None:
    client = TestClient(create_app())
    resp = client.post("/event", json=[1, 2, 3])
    assert resp.status_code == 400


def test_alert_response_endpoint_handles_press_one() -> None:
    client = TestClient(create_app())
    resp = client.post("/voice/alert-response", data={"Digits": "1", "CallSid": "CA123"})
    assert resp.status_code == 200
    assert "Neighbor notification request received" in resp.text


def test_alert_response_endpoint_handles_invalid_input() -> None:
    client = TestClient(create_app())
    resp = client.post("/voice/alert-response", data={"Digits": "9"})
    assert resp.status_code == 200
    assert "No valid selection was received" in resp.text
