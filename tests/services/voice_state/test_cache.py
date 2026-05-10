from __future__ import annotations

from services.voice_state import cache


def test_publish_and_read_round_trip() -> None:
    payload = {
        "incident_id": "inc_1",
        "homeowner_id": "hwn_alice",
        "tier": 3,
        "tier_name": "ALERT",
        "one_line_summary": "person reaching toward porch package",
        "scene": "the front porch",
        "behavior_pattern": "taking_item",
    }
    assert cache.publish_active_incident(payload, action_result={"actions": ["call_homeowner"]})
    body = cache.get_active_incident_for_homeowner("hwn_alice")
    assert body is not None
    assert body["incident_id"] == "inc_1"
    assert body["tier"] == 3
    assert "call_homeowner" in body["actions"]


def test_publish_skips_when_ids_missing() -> None:
    assert not cache.publish_active_incident({"tier": 3})
    assert cache.get_active_incident_for_homeowner("nobody") is None


def test_clear_drops_pointer_and_payload() -> None:
    cache.publish_active_incident({"incident_id": "inc_1", "homeowner_id": "hwn_alice", "tier": 3})
    cache.clear_active_incident("inc_1", "hwn_alice")
    assert cache.get_active_incident_for_homeowner("hwn_alice") is None


def test_two_homeowners_dont_collide() -> None:
    cache.publish_active_incident({"incident_id": "inc_a", "homeowner_id": "hwn_alice", "tier": 3})
    cache.publish_active_incident({"incident_id": "inc_b", "homeowner_id": "hwn_bob", "tier": 4})

    a = cache.get_active_incident_for_homeowner("hwn_alice")
    b = cache.get_active_incident_for_homeowner("hwn_bob")
    assert a is not None and a["incident_id"] == "inc_a"
    assert b is not None and b["incident_id"] == "inc_b"
