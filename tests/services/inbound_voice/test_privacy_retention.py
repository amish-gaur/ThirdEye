from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.inbound_voice.privacy import retention


def _seed_recording(fake_db, *, homeowner_id: str, recording_id: str, retain_until) -> None:
    fake_db["call_recordings"].insert_one(
        {
            "recording_id": recording_id,
            "homeowner_id": homeowner_id,
            "encrypted_object_key": f"r2://thirdeye/{recording_id}",
            "dek_wrapped_b64": "fake==",
            "retain_until": retain_until,
            "deleted_at": None,
        }
    )


def test_compute_retain_until_uses_default_when_no_settings() -> None:
    deadline = retention.compute_retain_until("hwn_alice", default_days=30)
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((deadline - expected).total_seconds()) < 5


def test_compute_retain_until_respects_homeowner_override(fake_db) -> None:
    fake_db["homeowner_privacy_settings"].insert_one(
        {"homeowner_id": "hwn_alice", "retention_days": 7}
    )
    deadline = retention.compute_retain_until("hwn_alice", default_days=30)
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((deadline - expected).total_seconds()) < 5


def test_sweep_deletes_only_expired(fake_db) -> None:
    now = datetime.now(timezone.utc)
    _seed_recording(fake_db, homeowner_id="h", recording_id="r_old", retain_until=now - timedelta(days=1))
    _seed_recording(fake_db, homeowner_id="h", recording_id="r_fresh", retain_until=now + timedelta(days=10))

    counts = retention.sweep_expired()
    assert counts == {"recordings": 1, "transcripts": 0}

    old = fake_db["call_recordings"].find_one({"recording_id": "r_old"})
    fresh = fake_db["call_recordings"].find_one({"recording_id": "r_fresh"})

    assert old["deleted_at"] is not None
    assert "dek_wrapped_b64" not in old  # cryptographic erasure
    assert "encrypted_object_key" not in old
    assert fresh["deleted_at"] is None
    assert fresh["dek_wrapped_b64"] == "fake=="


def test_sweep_creates_audit_entries(fake_db) -> None:
    now = datetime.now(timezone.utc)
    _seed_recording(fake_db, homeowner_id="h", recording_id="r_1", retain_until=now - timedelta(seconds=1))
    retention.sweep_expired()
    entries = list(fake_db["privacy_audit_log"].find({"homeowner_id": "h"}))
    assert len(entries) == 1
    assert entries[0]["action"] == "recording_deleted"
    assert entries[0]["metadata"]["reason"] == "retention_window_expired"
