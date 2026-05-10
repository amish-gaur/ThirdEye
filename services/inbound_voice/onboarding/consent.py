"""Typed consent state machine.

Every consent state change is:
1. Persisted to `consent_records` (one document per (homeowner, type) — we keep
   the latest state plus history via the audit log).
2. Audit-logged with the policy version, jurisdiction, and request metadata.

Rules:
- Consent is type-scoped (RECORDING ≠ VOICE_BIOMETRIC). Granting one does not
  grant another.
- Revocation is always honored immediately. A revoked consent disables all
  features that depend on it within the same request cycle.
- Consent records are NEVER hard-deleted, even on right-to-erasure: we
  tombstone with `state=revoked` so we can prove the homeowner once
  consented and then withdrew. Required by most jurisdictions.

Privacy policy versioning: this lane holds the current version as a constant.
Bumping the version means existing consents are still valid (we never
silently invalidate), but the homeowner sees a "policy updated" surface in
the mobile app prompting re-consent if material changes affect them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo.database import Database

from ..internal import mongo as mongo_mod
from ..internal.mongo import COLL_CONSENT
from ..models import AuditAction, ConsentRecord, ConsentState, ConsentType
from ..privacy import audit

log = logging.getLogger("inbound_voice.onboarding.consent")

# Bump on material privacy-policy changes. Existing consents remain valid;
# the mobile app surfaces a "review updated policy" prompt.
POLICY_VERSION = "2026-05-09"


def upsert_consent(
    *,
    homeowner_id: str,
    consent_type: ConsentType,
    state: ConsentState,
    jurisdiction: str,
    actor: str = "homeowner",
    source_ip: str | None = None,
    user_agent: str | None = None,
    db: Database | None = None,
) -> ConsentRecord:
    """Record a consent state change. Idempotent for the same target state."""
    database = db if db is not None else mongo_mod.get_db()
    now = datetime.now(timezone.utc)
    coll = database[COLL_CONSENT]

    existing = coll.find_one(
        {"homeowner_id": homeowner_id, "consent_type": consent_type.value}
    )
    if existing and existing.get("state") == state.value:
        existing.pop("_id", None)
        return ConsentRecord.model_validate(existing)

    doc = {
        "homeowner_id": homeowner_id,
        "consent_type": consent_type.value,
        "state": state.value,
        "jurisdiction": jurisdiction,
        "policy_version": POLICY_VERSION,
        "granted_at": now if state is ConsentState.GRANTED else (existing or {}).get("granted_at"),
        "revoked_at": now if state is ConsentState.REVOKED else None,
        "source_ip": source_ip,
        "user_agent": user_agent,
    }
    coll.update_one(
        {"homeowner_id": homeowner_id, "consent_type": consent_type.value},
        {"$set": doc},
        upsert=True,
    )

    audit.append(
        homeowner_id=homeowner_id,
        actor=actor,
        action=(
            AuditAction.CONSENT_GRANTED
            if state is ConsentState.GRANTED
            else AuditAction.CONSENT_REVOKED
        ),
        resource_type="consent",
        resource_id=consent_type.value,
        metadata={
            "jurisdiction": jurisdiction,
            "policy_version": POLICY_VERSION,
            "source_ip": source_ip,
            "user_agent": user_agent,
        },
    )
    return ConsentRecord.model_validate(doc)


def get_active_consents(
    *, homeowner_id: str, db: Database | None = None
) -> list[ConsentRecord]:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_CONSENT]
    out: list[ConsentRecord] = []
    for doc in coll.find({"homeowner_id": homeowner_id}):
        doc.pop("_id", None)
        out.append(ConsentRecord.model_validate(doc))
    return out


def has_consent(
    *,
    homeowner_id: str,
    consent_type: ConsentType,
    db: Database | None = None,
) -> bool:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_CONSENT]
    doc = coll.find_one(
        {"homeowner_id": homeowner_id, "consent_type": consent_type.value},
        projection={"state": 1},
    )
    return bool(doc and doc.get("state") == ConsentState.GRANTED.value)


def require_consent(
    *,
    homeowner_id: str,
    consent_type: ConsentType,
    db: Database | None = None,
) -> None:
    """Raise PermissionError if consent is not granted. Endpoints catch and
    convert to a 403 with a code the mobile app can match on."""
    if not has_consent(homeowner_id=homeowner_id, consent_type=consent_type, db=db):
        raise ConsentRequiredError(consent_type)


class ConsentRequiredError(PermissionError):
    def __init__(self, consent_type: ConsentType) -> None:
        super().__init__(f"consent required: {consent_type.value}")
        self.consent_type = consent_type
