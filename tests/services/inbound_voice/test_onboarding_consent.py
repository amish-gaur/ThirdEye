from __future__ import annotations

import pytest

from services.inbound_voice.models import ConsentState, ConsentType
from services.inbound_voice.onboarding.consent import (
    ConsentRequiredError,
    has_consent,
    require_consent,
    upsert_consent,
)


def test_grant_consent_persists_and_audits() -> None:
    record = upsert_consent(
        homeowner_id="hwn_alice",
        consent_type=ConsentType.RECORDING,
        state=ConsentState.GRANTED,
        jurisdiction="US-CA",
    )
    assert record.state == ConsentState.GRANTED
    assert record.granted_at is not None
    assert record.policy_version
    assert has_consent(homeowner_id="hwn_alice", consent_type=ConsentType.RECORDING)


def test_revoke_consent_immediately_disables_feature() -> None:
    upsert_consent(
        homeowner_id="hwn_alice",
        consent_type=ConsentType.RECORDING,
        state=ConsentState.GRANTED,
        jurisdiction="US-CA",
    )
    upsert_consent(
        homeowner_id="hwn_alice",
        consent_type=ConsentType.RECORDING,
        state=ConsentState.REVOKED,
        jurisdiction="US-CA",
    )
    assert not has_consent(homeowner_id="hwn_alice", consent_type=ConsentType.RECORDING)


def test_consent_is_type_scoped() -> None:
    upsert_consent(
        homeowner_id="hwn_alice",
        consent_type=ConsentType.RECORDING,
        state=ConsentState.GRANTED,
        jurisdiction="US-CA",
    )
    assert has_consent(homeowner_id="hwn_alice", consent_type=ConsentType.RECORDING)
    assert not has_consent(homeowner_id="hwn_alice", consent_type=ConsentType.VOICE_BIOMETRIC)


def test_require_consent_raises_when_missing() -> None:
    with pytest.raises(ConsentRequiredError) as exc:
        require_consent(homeowner_id="hwn_alice", consent_type=ConsentType.VOICE_BIOMETRIC)
    assert exc.value.consent_type is ConsentType.VOICE_BIOMETRIC


def test_idempotent_same_state_no_history_explosion(fake_db) -> None:
    for _ in range(3):
        upsert_consent(
            homeowner_id="hwn_alice",
            consent_type=ConsentType.RECORDING,
            state=ConsentState.GRANTED,
            jurisdiction="US-CA",
        )
    # Audit log should have exactly 1 entry — idempotency guarantee.
    n = fake_db["privacy_audit_log"].count_documents({"homeowner_id": "hwn_alice"})
    assert n == 1
