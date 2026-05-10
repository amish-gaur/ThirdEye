from __future__ import annotations

from services.inbound_voice.models import EmergencyContactRole
from services.inbound_voice.onboarding.emergency_contacts import (
    accept_invite,
    invite,
    list_active,
    revoke,
)


def test_invite_starts_pending_and_not_active() -> None:
    contact, token = invite(
        homeowner_id="hwn_alice",
        role=EmergencyContactRole.FAMILY,
        name="Mom",
        phone="+15555550123",
    )
    assert contact.consented_at is None
    assert token  # caller is responsible for SMS-ing it
    assert list_active(homeowner_id="hwn_alice") == []  # not active until accepted


def test_accept_marks_active() -> None:
    contact, token = invite(
        homeowner_id="hwn_alice",
        role=EmergencyContactRole.FAMILY,
        name="Mom",
        phone="+15555550123",
    )
    assert accept_invite(contact_id=contact.contact_id, consent_token=token)
    actives = list_active(homeowner_id="hwn_alice")
    assert len(actives) == 1
    assert actives[0].contact_id == contact.contact_id


def test_wrong_token_rejected() -> None:
    contact, _ = invite(
        homeowner_id="hwn_alice",
        role=EmergencyContactRole.FAMILY,
        name="Mom",
        phone="+15555550123",
    )
    assert not accept_invite(contact_id=contact.contact_id, consent_token="wrong")


def test_revoke_removes_from_active() -> None:
    contact, token = invite(
        homeowner_id="hwn_alice",
        role=EmergencyContactRole.NEIGHBOR,
        name="Bob",
        phone="+15555550101",
    )
    accept_invite(contact_id=contact.contact_id, consent_token=token)
    assert revoke(contact_id=contact.contact_id, actor="homeowner")
    assert list_active(homeowner_id="hwn_alice") == []


def test_accept_is_idempotent() -> None:
    contact, token = invite(
        homeowner_id="hwn_alice",
        role=EmergencyContactRole.FAMILY,
        name="Mom",
        phone="+15555550123",
    )
    assert accept_invite(contact_id=contact.contact_id, consent_token=token)
    assert accept_invite(contact_id=contact.contact_id, consent_token=token)  # again
