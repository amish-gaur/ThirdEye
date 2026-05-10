"""Phone-number verification.

Backed by Twilio Verify in production (`TwilioVerifier`) and an in-memory
implementation for tests (`InMemoryVerifier`). Both share the same
`Verifier` protocol so call sites are identical.

Rate-limited via Redis: per-homeowner and per-phone counters with a sliding
window. Abuse-resistant: checks are constant-time-ish (we compare
fixed-length codes only after the input has the expected shape).
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import CONFIG
from ..internal import redis_client
from ..internal.twilio_client import get_client
from ..models import AuditAction
from ..privacy import audit

log = logging.getLogger("inbound_voice.onboarding.verification")


class Verifier(Protocol):
    def send_code(self, phone: str) -> None: ...
    def check_code(self, phone: str, code: str) -> bool: ...


# ---- Twilio Verify ---------------------------------------------------------


@dataclass(frozen=True)
class TwilioVerifier:
    service_sid: str

    def send_code(self, phone: str) -> None:
        get_client().verify.v2.services(self.service_sid).verifications.create(
            to=phone, channel="sms"
        )

    def check_code(self, phone: str, code: str) -> bool:
        resp = (
            get_client()
            .verify.v2.services(self.service_sid)
            .verification_checks.create(to=phone, code=code)
        )
        return getattr(resp, "status", "") == "approved"


# ---- In-memory (tests) -----------------------------------------------------


@dataclass
class InMemoryVerifier:
    """Stores hashed codes in a dict; tests can introspect via `last_code`."""

    sent: dict[str, str]  # phone -> code (plain, for tests only)

    def __init__(self) -> None:
        self.sent = {}

    def send_code(self, phone: str) -> None:
        self.sent[phone] = "{:06d}".format(secrets.randbelow(1_000_000))

    def check_code(self, phone: str, code: str) -> bool:
        expected = self.sent.get(phone)
        if not expected or len(expected) != len(code):
            return False
        return hmac.compare_digest(expected, code)

    def last_code(self, phone: str) -> str | None:
        return self.sent.get(phone)


# ---- Rate limiting ---------------------------------------------------------


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


def rate_limit_send(
    *, homeowner_id: str, phone: str, redis: Any | None = None
) -> RateLimitDecision:
    """Cap: 5 sends/hour/homeowner, 3 sends/hour/phone."""
    r = redis if redis is not None else redis_client.get_redis()
    now = int(time.time())

    h_key = f"verify:send:hwn:{homeowner_id}"
    p_key = f"verify:send:phone:{phone}"
    h_n = _bump(r, h_key, now, window=3600, cap=5)
    p_n = _bump(r, p_key, now, window=3600, cap=3)
    if h_n is None or p_n is None:
        ttl = max(int(r.ttl(h_key) or 0), int(r.ttl(p_key) or 0))
        return RateLimitDecision(allowed=False, retry_after_seconds=max(ttl, 1))
    return RateLimitDecision(allowed=True, retry_after_seconds=0)


def rate_limit_check(*, phone: str, redis: Any | None = None) -> RateLimitDecision:
    """Cap: 5 attempts/hour/phone. Brute force is cheap to mitigate here."""
    r = redis if redis is not None else redis_client.get_redis()
    now = int(time.time())
    key = f"verify:check:phone:{phone}"
    n = _bump(r, key, now, window=3600, cap=CONFIG.verification_max_attempts)
    if n is None:
        ttl = int(r.ttl(key) or 0)
        return RateLimitDecision(allowed=False, retry_after_seconds=max(ttl, 1))
    return RateLimitDecision(allowed=True, retry_after_seconds=0)


def _bump(r: Any, key: str, now: int, *, window: int, cap: int) -> int | None:
    """Returns the new count, or None if cap exceeded. Window resets on first hit."""
    n = r.incr(key)
    if n == 1:
        r.expire(key, window)
    if n > cap:
        return None
    return int(n)


# ---- Orchestration ---------------------------------------------------------


def start_verification(
    *,
    homeowner_id: str,
    phone: str,
    verifier: Verifier,
    redis: Any | None = None,
) -> RateLimitDecision:
    decision = rate_limit_send(homeowner_id=homeowner_id, phone=phone, redis=redis)
    if not decision.allowed:
        log.warning("rate-limited verification send homeowner=%s phone=%s", homeowner_id, phone)
        return decision
    verifier.send_code(phone)
    audit.append(
        homeowner_id=homeowner_id,
        actor="homeowner",
        action=AuditAction.PHONE_VERIFICATION_SENT,
        resource_type="phone",
        resource_id=phone,
    )
    return decision


def check_verification(
    *,
    homeowner_id: str,
    phone: str,
    code: str,
    verifier: Verifier,
    redis: Any | None = None,
) -> bool:
    decision = rate_limit_check(phone=phone, redis=redis)
    if not decision.allowed:
        log.warning("rate-limited verification check phone=%s", phone)
        audit.append(
            homeowner_id=homeowner_id,
            actor="homeowner",
            action=AuditAction.PHONE_VERIFICATION_FAILED,
            resource_type="phone",
            resource_id=phone,
            metadata={"reason": "rate_limited"},
        )
        return False
    ok = verifier.check_code(phone, code)
    audit.append(
        homeowner_id=homeowner_id,
        actor="homeowner",
        action=(
            AuditAction.PHONE_VERIFICATION_SUCCEEDED
            if ok
            else AuditAction.PHONE_VERIFICATION_FAILED
        ),
        resource_type="phone",
        resource_id=phone,
    )
    return ok
