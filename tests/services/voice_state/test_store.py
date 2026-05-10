from __future__ import annotations

from services.voice_state import store
from services.voice_state.models import (
    CallDirection,
    IncidentVoiceState,
    LegState,
)


def _register_outbound(incident_id: str, call_sid: str, target: str = "homeowner") -> None:
    store.register_leg(
        incident_id=incident_id,
        homeowner_id="hwn_alice",
        call_sid=call_sid,
        direction=CallDirection.OUTBOUND,
        target_label=target,
        target_phone="+15555550100",
    )


def test_register_leg_creates_incident_and_leg() -> None:
    leg = store.register_leg(
        incident_id="inc_1",
        homeowner_id="hwn_alice",
        call_sid="CA001",
        direction=CallDirection.OUTBOUND,
        target_label="homeowner",
        target_phone="+15555550100",
    )
    assert leg.state is LegState.RINGING
    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.OPEN
    assert len(incident.legs) == 1


def test_register_leg_is_idempotent() -> None:
    _register_outbound("inc_1", "CA001")
    _register_outbound("inc_1", "CA001")  # same SID
    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert len(incident.legs) == 1


def test_update_leg_state_transitions() -> None:
    _register_outbound("inc_1", "CA001")
    leg = store.update_leg_state(call_sid="CA001", new_state=LegState.ANSWERED)
    assert leg is not None
    assert leg.state is LegState.ANSWERED
    assert leg.answered_at is not None


def test_terminal_state_is_sticky() -> None:
    _register_outbound("inc_1", "CA001")
    store.update_leg_state(call_sid="CA001", new_state=LegState.COMPLETED)
    leg = store.update_leg_state(call_sid="CA001", new_state=LegState.ANSWERED)
    # Should NOT regress out of COMPLETED.
    assert leg is not None
    assert leg.state is LegState.COMPLETED


def test_first_to_acknowledge_wins_and_cancels_others() -> None:
    _register_outbound("inc_1", "CA001", "homeowner")
    _register_outbound("inc_1", "CA002", "family")
    _register_outbound("inc_1", "CA003", "dispatch")

    accepted, cancelled = store.declare_winner(incident_id="inc_1", call_sid="CA001")
    assert accepted
    assert sorted(cancelled) == ["CA002", "CA003"]

    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.ACKNOWLEDGED
    assert incident.winner_call_sid == "CA001"

    states = {leg.call_sid: leg.state for leg in incident.legs}
    assert states["CA001"] is LegState.ANSWERED
    assert states["CA002"] is LegState.CANCELLED
    assert states["CA003"] is LegState.CANCELLED


def test_second_winner_attempt_is_rejected() -> None:
    _register_outbound("inc_1", "CA001")
    _register_outbound("inc_1", "CA002")
    store.declare_winner(incident_id="inc_1", call_sid="CA001")

    accepted, cancelled = store.declare_winner(incident_id="inc_1", call_sid="CA002")
    assert not accepted
    assert cancelled == []


def test_idempotent_winner_reclaim() -> None:
    _register_outbound("inc_1", "CA001")
    store.declare_winner(incident_id="inc_1", call_sid="CA001")
    accepted, cancelled = store.declare_winner(incident_id="inc_1", call_sid="CA001")
    assert accepted
    assert cancelled == []


def test_cancel_incident_terminates_all_open_legs() -> None:
    _register_outbound("inc_1", "CA001")
    _register_outbound("inc_1", "CA002")
    n = store.cancel_incident(incident_id="inc_1")
    assert n == 2
    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.CANCELLED
    for leg in incident.legs:
        assert leg.state is LegState.CANCELLED


def test_resolved_when_all_legs_terminal_no_winner() -> None:
    _register_outbound("inc_1", "CA001")
    _register_outbound("inc_1", "CA002")
    store.update_leg_state(call_sid="CA001", new_state=LegState.NO_ANSWER)
    store.update_leg_state(call_sid="CA002", new_state=LegState.NO_ANSWER)
    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    assert incident.state is IncidentVoiceState.RESOLVED


def test_winner_keeps_acknowledged_state_even_after_other_legs_complete() -> None:
    _register_outbound("inc_1", "CA001")
    _register_outbound("inc_1", "CA002")
    store.declare_winner(incident_id="inc_1", call_sid="CA001")
    store.update_leg_state(call_sid="CA002", new_state=LegState.COMPLETED)

    incident = store.get_incident(incident_id="inc_1")
    assert incident is not None
    # Should remain ACKNOWLEDGED — winner exists.
    assert incident.state is IncidentVoiceState.ACKNOWLEDGED
