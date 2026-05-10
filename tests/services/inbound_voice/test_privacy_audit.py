from __future__ import annotations

from services.inbound_voice.models import AuditAction
from services.inbound_voice.privacy import audit


def test_first_entry_has_empty_prev_hash() -> None:
    entry = audit.append(
        homeowner_id="hwn_alice",
        actor="homeowner",
        action=AuditAction.CONSENT_GRANTED,
        resource_type="consent",
        resource_id="recording",
    )
    assert entry.seq == 1
    assert entry.prev_hash == ""
    assert len(entry.hash) == 64  # sha-256 hex


def test_chain_links_correctly() -> None:
    a = audit.append(
        homeowner_id="hwn_alice",
        actor="homeowner",
        action=AuditAction.CONSENT_GRANTED,
        resource_type="consent",
        resource_id="recording",
    )
    b = audit.append(
        homeowner_id="hwn_alice",
        actor="homeowner",
        action=AuditAction.CONSENT_REVOKED,
        resource_type="consent",
        resource_id="recording",
    )
    assert b.seq == 2
    assert b.prev_hash == a.hash


def test_separate_homeowners_have_independent_chains() -> None:
    a1 = audit.append(
        homeowner_id="hwn_alice",
        actor="homeowner",
        action=AuditAction.CONSENT_GRANTED,
    )
    b1 = audit.append(
        homeowner_id="hwn_bob",
        actor="homeowner",
        action=AuditAction.CONSENT_GRANTED,
    )
    a2 = audit.append(
        homeowner_id="hwn_alice",
        actor="homeowner",
        action=AuditAction.CONSENT_REVOKED,
    )
    assert b1.seq == 1
    assert a2.prev_hash == a1.hash  # alice's chain unaffected by bob


def test_verify_chain_passes_on_clean_log() -> None:
    for action in (AuditAction.CONSENT_GRANTED, AuditAction.CONSENT_REVOKED) * 5:
        audit.append(homeowner_id="hwn_alice", actor="homeowner", action=action)
    ok, count = audit.verify_chain(homeowner_id="hwn_alice")
    assert ok
    assert count == 10


def test_verify_chain_detects_tampering(fake_db) -> None:
    audit.append(homeowner_id="hwn_alice", actor="homeowner", action=AuditAction.CONSENT_GRANTED)
    audit.append(homeowner_id="hwn_alice", actor="homeowner", action=AuditAction.CONSENT_REVOKED)

    # Tamper with the second entry's metadata (a privacy-relevant field).
    fake_db["privacy_audit_log"].update_one(
        {"homeowner_id": "hwn_alice", "seq": 2},
        {"$set": {"actor": "attacker"}},
    )

    ok, count = audit.verify_chain(homeowner_id="hwn_alice")
    assert not ok
    assert count == 1  # first entry verified, then mismatch detected
