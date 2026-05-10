from __future__ import annotations

from services.inbound_voice.onboarding.verification import (
    InMemoryVerifier,
    check_verification,
    rate_limit_check,
    rate_limit_send,
    start_verification,
)


def test_send_and_check_round_trip() -> None:
    verifier = InMemoryVerifier()
    start_verification(homeowner_id="hwn_alice", phone="+15555550100", verifier=verifier)
    code = verifier.last_code("+15555550100")
    assert code is not None
    assert check_verification(
        homeowner_id="hwn_alice",
        phone="+15555550100",
        code=code,
        verifier=verifier,
    )


def test_wrong_code_fails() -> None:
    verifier = InMemoryVerifier()
    start_verification(homeowner_id="hwn_alice", phone="+15555550100", verifier=verifier)
    assert not check_verification(
        homeowner_id="hwn_alice",
        phone="+15555550100",
        code="000000",
        verifier=verifier,
    )


def test_send_rate_limit_per_homeowner() -> None:
    """Cap is 5/hour per homeowner. The 6th send must be blocked.

    Use a fresh phone each iteration so the per-phone cap (3) doesn't trip
    first — this test isolates the per-homeowner ceiling.
    """
    verifier = InMemoryVerifier()
    for i in range(5):
        decision = start_verification(
            homeowner_id="hwn_alice", phone=f"+155555501{i:02d}", verifier=verifier
        )
        assert decision.allowed
    decision = start_verification(
        homeowner_id="hwn_alice", phone="+15555550199", verifier=verifier
    )
    assert not decision.allowed
    assert decision.retry_after_seconds > 0


def test_send_rate_limit_per_phone() -> None:
    """Cap is 3/hour per phone — even across homeowners (anti-abuse)."""
    verifier = InMemoryVerifier()
    for i in range(3):
        decision = rate_limit_send(homeowner_id=f"hwn_{i}", phone="+15555550100")
        assert decision.allowed
    decision = rate_limit_send(homeowner_id="hwn_4", phone="+15555550100")
    assert not decision.allowed


def test_check_rate_limit() -> None:
    """5 attempts/hour/phone (default)."""
    for _ in range(5):
        decision = rate_limit_check(phone="+15555550100")
        assert decision.allowed
    assert not rate_limit_check(phone="+15555550100").allowed
