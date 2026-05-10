"""Voice-biometric enrollment.

Privacy stance: we never store raw audio. The mobile app computes a small
embedding (mel-spectrogram → 64-d float vector) locally, normalizes it, and
sends us only a SHA-256 hash of (embedding || homeowner-secret). We can
verify a future utterance by recomputing the hash with the same secret.

We also enforce that the homeowner has granted VOICE_BIOMETRIC consent
before anything is persisted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo.database import Database

from ..internal import mongo as mongo_mod
from ..internal.mongo import COLL_VOICE_PROFILES
from ..models import AuditAction, ConsentType
from ..privacy import audit
from .consent import require_consent

log = logging.getLogger("inbound_voice.onboarding.voice_profile")


def enroll(
    *,
    homeowner_id: str,
    fingerprint_hash: str,
    sample_count: int,
    db: Database | None = None,
) -> None:
    require_consent(homeowner_id=homeowner_id, consent_type=ConsentType.VOICE_BIOMETRIC, db=db)
    coll = (db if db is not None else mongo_mod.get_db())[COLL_VOICE_PROFILES]
    coll.update_one(
        {"homeowner_id": homeowner_id, "deleted_at": None},
        {
            "$set": {
                "fingerprint_hash": fingerprint_hash,
                "sample_count": sample_count,
                "enrolled_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    audit.append(
        homeowner_id=homeowner_id,
        actor="homeowner",
        action=AuditAction.VOICE_PROFILE_ENROLLED,
        resource_type="voice_profile",
        resource_id=homeowner_id,
        metadata={"sample_count": sample_count},
    )


def is_enrolled(*, homeowner_id: str, db: Database | None = None) -> bool:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_VOICE_PROFILES]
    return bool(
        coll.find_one(
            {"homeowner_id": homeowner_id, "deleted_at": None, "fingerprint_hash": {"$exists": True}},
            projection={"_id": 1},
        )
    )


def delete(*, homeowner_id: str, db: Database | None = None) -> bool:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_VOICE_PROFILES]
    result = coll.update_many(
        {"homeowner_id": homeowner_id, "deleted_at": None},
        {"$set": {"deleted_at": datetime.now(timezone.utc)}, "$unset": {"fingerprint_hash": ""}},
    )
    if result.modified_count:
        audit.append(
            homeowner_id=homeowner_id,
            actor="homeowner",
            action=AuditAction.VOICE_PROFILE_DELETED,
            resource_type="voice_profile",
            resource_id=homeowner_id,
        )
    return result.modified_count > 0
