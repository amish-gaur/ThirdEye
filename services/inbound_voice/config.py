"""Env-driven config for the inbound-voice service.

Kept separate from `action_router.config` so this lane can be deployed
independently (e.g. behind its own ngrok subdomain for the Twilio webhook).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class InboundVoiceConfig:
    # Twilio
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from_number: str = os.getenv("TWILIO_FROM_NUMBER", "")
    twilio_verify_service_sid: str = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")

    # Redis (state machine + verification rate limit)
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # Mongo (consent records, voice profiles, audit log, retention metadata)
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    mongo_db: str = os.getenv("MONGO_DB", "safewatch")

    # R2 / S3 for encrypted recordings
    r2_account_id: str = os.getenv("R2_ACCOUNT_ID", "")
    r2_access_key_id: str = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret_access_key: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
    r2_bucket: str = os.getenv("R2_BUCKET", "safewatch-recordings")

    # Privacy: KMS master key (hex-encoded 32 bytes for software KMS).
    # In production, swap to AWS KMS / GCP KMS via internal/kms.py.
    kms_master_key_hex: str = os.getenv("SAFEWATCH_KMS_MASTER_KEY", "")

    # Retention (days) — homeowner can override per-account. This is the floor.
    default_retention_days: int = _int("DEFAULT_RETENTION_DAYS", 30)
    erasure_grace_period_days: int = _int("ERASURE_GRACE_PERIOD_DAYS", 7)

    # Onboarding
    verification_code_ttl_seconds: int = _int("VERIFICATION_CODE_TTL_SECONDS", 600)
    verification_max_attempts: int = _int("VERIFICATION_MAX_ATTEMPTS", 5)

    # Auth (Clerk JWKS — stub-friendly; real verifier lands when lane/live-query
    # publishes services/_shared/auth.py)
    clerk_jwks_url: str = os.getenv("CLERK_JWKS_URL", "")
    clerk_issuer: str = os.getenv("CLERK_ISSUER", "")

    # Coordination
    rishab_agent_ws_url: str = os.getenv("RISHAB_AGENT_WS_URL", "")  # falls back to <Say> IVR

    # Service
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    dry_run: bool = _bool("DRY_RUN", False)

    def has_twilio(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    def has_kms_key(self) -> bool:
        return len(self.kms_master_key_hex) == 64  # 32 bytes hex

    def default_retention(self) -> timedelta:
        return timedelta(days=self.default_retention_days)

    def erasure_grace_period(self) -> timedelta:
        return timedelta(days=self.erasure_grace_period_days)


CONFIG = InboundVoiceConfig()
