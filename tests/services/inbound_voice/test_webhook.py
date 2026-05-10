from __future__ import annotations

from fastapi.testclient import TestClient

from services.inbound_voice.app import create_app
from services.inbound_voice.phones import record_verified
from services.voice_state import cache, store
from services.voice_state.models import CallDirection, IncidentVoiceState, LegState


def _client() -> TestClient:
    return TestClient(create_app())


# ---- /inbound/voice ---------------------------------------------------------


def test_unknown_caller_gets_polite_hangup() -> None:
    resp = _client().post(
        "/inbound/voice",
        data={"From": "+15555550999", "CallSid": "CA001"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Hangup/>" in body
    assert "homeowner" in body.lower() or "verified" in body.lower()


def test_known_caller_no_active_incident_briefing() -> None:
    record_verified(homeowner_id="hwn_alice", phone="+15555550100")
    resp = _client().post(
        "/inbound/voice",
        data={"From": "+15555550100", "CallSid": "CA001"},
    )
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "no active alerts" in body or "currently quiet" in body
    assert "<gather" not in body  # no IVR when nothing's happening


def test_known_caller_active_incident_gets_ivr() -> None:
    record_verified(homeowner_id="hwn_alice", phone="+15555550100")
    cache.publish_active_incident({
        "incident_id": "inc_1",
        "homeowner_id": "hwn_alice",
        "tier": 3,
        "tier_name": "ALERT",
        "one_line_summary": "person reaching toward porch package",
        "scene": "the front porch",
        "behavior_pattern": "taking_item",
    })
    resp = _client().post(
        "/inbound/voice",
        data={"From": "+15555550100", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Gather" in body
    assert "Press 1 to acknowledge" in body
    assert "Press 2 to cancel" in body
    assert "Press 3 to escalate" in body
    assert "porch" in body  # scene rendered

    # Inbound leg registered + answered
    leg = store.get_leg(call_sid="CAIN1")
    assert leg is not None
    assert leg.direction is CallDirection.INBOUND
    assert leg.state is LegState.ANSWERED


# ---- /inbound/voice/dtmf ----------------------------------------------------


def _stage_active_incident_with_outbound() -> None:
    record_verified(homeowner_id="hwn_alice", phone="+15555550100")
    cache.publish_active_incident({
        "incident_id": "inc_1",
        "homeowner_id": "hwn_alice",
        "tier": 3,
        "one_line_summary": "porch theft suspect",
    })
    # Pre-existing outbound leg (Rishab's lane already dialed)
    store.register_leg(
        incident_id="inc_1",
        homeowner_id="hwn_alice",
        call_sid="CAOUT1",
        direction=CallDirection.OUTBOUND,
        target_label="family",
        target_phone="+15555550101",
    )


def test_dtmf_1_acknowledges_and_cancels_other_legs() -> None:
    _stage_active_incident_with_outbound()
    client = _client()

    # Inbound call lands first, registers the leg
    client.post("/inbound/voice", data={"From": "+15555550100", "CallSid": "CAIN1"})

    # User presses 1
    resp = client.post(
        "/inbound/voice/dtmf?incident_id=inc_1",
        data={"Digits": "1", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    assert "Acknowledged" in resp.text

    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.ACKNOWLEDGED
    assert incident.winner_call_sid == "CAIN1"
    states = {leg.call_sid: leg.state for leg in incident.legs}
    assert states["CAIN1"] is LegState.ANSWERED
    assert states["CAOUT1"] is LegState.CANCELLED

    # Active-incident cache cleared so subsequent inbound calls show "quiet"
    assert cache.get_active_incident_for_homeowner("hwn_alice") is None


def test_dtmf_1_when_already_won_says_already_responded() -> None:
    _stage_active_incident_with_outbound()
    # Outbound leg "won" first (e.g., family member answered)
    store.declare_winner(incident_id="inc_1", call_sid="CAOUT1")

    client = _client()
    client.post("/inbound/voice", data={"From": "+15555550100", "CallSid": "CAIN1"})
    resp = client.post(
        "/inbound/voice/dtmf?incident_id=inc_1",
        data={"Digits": "1", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    assert "already responded" in resp.text.lower()


def test_dtmf_2_cancels_entire_incident() -> None:
    _stage_active_incident_with_outbound()
    client = _client()
    client.post("/inbound/voice", data={"From": "+15555550100", "CallSid": "CAIN1"})

    resp = client.post(
        "/inbound/voice/dtmf?incident_id=inc_1",
        data={"Digits": "2", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    assert "Cancelled" in resp.text

    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.CANCELLED


def test_dtmf_invalid_says_goodbye() -> None:
    _stage_active_incident_with_outbound()
    client = _client()
    client.post("/inbound/voice", data={"From": "+15555550100", "CallSid": "CAIN1"})

    resp = client.post(
        "/inbound/voice/dtmf?incident_id=inc_1",
        data={"Digits": "9", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    assert "<Hangup/>" in resp.text


def test_dtmf_without_incident_id_hangs_up_cleanly() -> None:
    resp = _client().post(
        "/inbound/voice/dtmf",
        data={"Digits": "1", "CallSid": "CAIN1"},
    )
    assert resp.status_code == 200
    assert "<Hangup/>" in resp.text


# ---- /inbound/voice/status --------------------------------------------------


def test_status_callback_updates_leg_state() -> None:
    store.register_leg(
        incident_id="inc_1",
        homeowner_id="hwn_alice",
        call_sid="CA001",
        direction=CallDirection.OUTBOUND,
        target_label="homeowner",
    )
    resp = _client().post(
        "/inbound/voice/status",
        data={"CallSid": "CA001", "CallStatus": "completed"},
    )
    assert resp.status_code == 204
    leg = store.get_leg(call_sid="CA001")
    assert leg is not None
    assert leg.state is LegState.COMPLETED


def test_status_callback_unknown_call_is_no_op() -> None:
    resp = _client().post(
        "/inbound/voice/status",
        data={"CallSid": "GHOST", "CallStatus": "completed"},
    )
    # Should not crash, even if no leg exists.
    assert resp.status_code == 204


# ---- /health ----------------------------------------------------------------


def test_health_endpoint() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "twilio_configured" in body
