from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.inbound_voice.models import ErasureScope
from services.inbound_voice.privacy import erasure


def _seed_recording(fake_db, **fields) -> None:
    fake_db["call_recordings"].insert_one({"deleted_at": None, **fields})


def _seed_transcript(fake_db, **fields) -> None:
    fake_db["call_transcripts"].insert_one({"deleted_at": None, **fields})


def _seed_voice_profile(fake_db, **fields) -> None:
    fake_db["voice_profiles"].insert_one({"deleted_at": None, **fields})


def test_request_erasure_persists_with_grace_period(fake_db) -> None:
    req = erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.RECORDINGS],
        actor="homeowner",
        grace_period=timedelta(days=7),
    )
    assert req["status"] == "pending"
    assert (req["scheduled_for"] - req["requested_at"]) == timedelta(days=7)


def test_cancel_within_grace_period(fake_db) -> None:
    req = erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.RECORDINGS],
        actor="homeowner",
        grace_period=timedelta(days=7),
    )
    assert erasure.cancel_erasure(request_id=req["request_id"], actor="homeowner")
    cancelled = fake_db["erasure_requests"].find_one({"request_id": req["request_id"]})
    assert cancelled["status"] == "cancelled"


def test_cannot_cancel_after_grace_period(fake_db) -> None:
    req = erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.RECORDINGS],
        actor="homeowner",
        grace_period=timedelta(seconds=-1),  # already past
    )
    assert not erasure.cancel_erasure(request_id=req["request_id"], actor="homeowner")


def test_execute_due_cryptographically_erases_recordings(fake_db) -> None:
    _seed_recording(
        fake_db,
        recording_id="r_1",
        homeowner_id="hwn_alice",
        encrypted_object_key="r2://x",
        dek_wrapped_b64="fake==",
    )
    erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.RECORDINGS],
        actor="homeowner",
        grace_period=timedelta(seconds=-1),
    )
    n = erasure.execute_due()
    assert n == 1

    rec = fake_db["call_recordings"].find_one({"recording_id": "r_1"})
    assert rec["deleted_at"] is not None
    assert "dek_wrapped_b64" not in rec
    assert "encrypted_object_key" not in rec


def test_everything_scope_cascades(fake_db) -> None:
    _seed_recording(
        fake_db,
        recording_id="r_1",
        homeowner_id="hwn_alice",
        encrypted_object_key="r2://x",
        dek_wrapped_b64="fake==",
    )
    _seed_transcript(
        fake_db,
        transcript_id="t_1",
        homeowner_id="hwn_alice",
        encrypted_object_key="r2://y",
        dek_wrapped_b64="fake==",
    )
    _seed_voice_profile(
        fake_db,
        homeowner_id="hwn_alice",
        fingerprint_hash="aa" * 32,
    )

    erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.EVERYTHING],
        actor="homeowner",
        grace_period=timedelta(seconds=-1),
    )
    erasure.execute_due()

    assert fake_db["call_recordings"].find_one({"recording_id": "r_1"})["deleted_at"]
    assert fake_db["call_transcripts"].find_one({"transcript_id": "t_1"})["deleted_at"]
    vp = fake_db["voice_profiles"].find_one({"homeowner_id": "hwn_alice"})
    assert vp["deleted_at"] is not None
    assert "fingerprint_hash" not in vp


def test_execution_is_audit_logged(fake_db) -> None:
    _seed_recording(
        fake_db,
        recording_id="r_1",
        homeowner_id="hwn_alice",
        encrypted_object_key="r2://x",
        dek_wrapped_b64="fake==",
    )
    erasure.request_erasure(
        homeowner_id="hwn_alice",
        scope=[ErasureScope.RECORDINGS],
        actor="homeowner",
        grace_period=timedelta(seconds=-1),
    )
    erasure.execute_due()

    audit_entries = list(fake_db["privacy_audit_log"].find({"homeowner_id": "hwn_alice"}))
    actions = [e["action"] for e in audit_entries]
    assert "erasure_requested" in actions
    assert "recording_deleted" in actions
    assert "erasure_executed" in actions
