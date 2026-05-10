"""Right-to-erasure: full or scoped deletion with a grace period.

Flow:
1. Homeowner requests erasure with a `scope` list and an optional immediate
   flag (defaults to grace period).
2. We schedule the erasure for `now + grace_period` and audit-log the request.
3. Until `scheduled_for`, the homeowner can cancel.
4. On execution, we cryptographically erase wrapped DEKs (recordings,
   transcripts), wipe voice-profile fingerprints, and audit-log each step.
5. Consent records are NOT deleted — we keep a tombstoned record so we can
   prove the homeowner once consented and then withdrew. Required by most
   jurisdictions.

Scopes:
    RECORDINGS  — call_recordings only
    TRANSCRIPTS — call_transcripts only
    VOICE_PROFILE — voice_profiles only
    EVERYTHING  — all of the above + emergency contacts (revoke their relay
                  consent) + future categories
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo.database import Database

from ..internal import mongo as mongo_mod
from ..internal.mongo import (
    COLL_EMERGENCY_CONTACTS,
    COLL_ERASURE_REQUESTS,
    COLL_RECORDINGS,
    COLL_TRANSCRIPTS,
    COLL_VOICE_PROFILES,
)
from ..models import AuditAction, ErasureScope
from . import audit

log = logging.getLogger("inbound_voice.privacy.erasure")


def request_erasure(
    *,
    homeowner_id: str,
    scope: list[ErasureScope],
    actor: str,
    grace_period: timedelta,
    db: Database | None = None,
) -> dict[str, Any]:
    """Schedule an erasure. Returns the persisted request doc."""
    if not scope:
        raise ValueError("scope must contain at least one ErasureScope")

    database = db if db is not None else mongo_mod.get_db()
    now = datetime.now(timezone.utc)
    request = {
        "request_id": f"era_{uuid.uuid4().hex[:12]}",
        "homeowner_id": homeowner_id,
        "scope": [s.value for s in scope],
        "requested_at": now,
        "scheduled_for": now + grace_period,
        "status": "pending",
        "completed_at": None,
    }
    database[COLL_ERASURE_REQUESTS].insert_one(dict(request))
    audit.append(
        homeowner_id=homeowner_id,
        actor=actor,
        action=AuditAction.ERASURE_REQUESTED,
        metadata={"scope": request["scope"], "scheduled_for": request["scheduled_for"].isoformat()},
    )
    return request


def cancel_erasure(
    *, request_id: str, actor: str, db: Database | None = None
) -> bool:
    """Cancel a pending erasure. Returns True if cancelled, False if too late."""
    database = db if db is not None else mongo_mod.get_db()
    now = datetime.now(timezone.utc)
    coll = database[COLL_ERASURE_REQUESTS]
    doc = coll.find_one_and_update(
        {"request_id": request_id, "status": "pending", "scheduled_for": {"$gt": now}},
        {"$set": {"status": "cancelled"}},
        return_document=True,  # ReturnDocument.AFTER == True in pymongo 4.x
    )
    if not doc:
        return False
    audit.append(
        homeowner_id=doc["homeowner_id"],
        actor=actor,
        action=AuditAction.ERASURE_CANCELLED,
        metadata={"request_id": request_id},
    )
    return True


def execute_due(*, db: Database | None = None) -> int:
    """Execute every erasure whose scheduled time has passed. Returns count."""
    database = db if db is not None else mongo_mod.get_db()
    now = datetime.now(timezone.utc)
    due = list(
        database[COLL_ERASURE_REQUESTS].find(
            {"status": "pending", "scheduled_for": {"$lte": now}}
        )
    )
    for req in due:
        _execute_one(database, req)
    return len(due)


# ---- internal ---------------------------------------------------------------


def _execute_one(db: Database, req: dict[str, Any]) -> None:
    homeowner_id = req["homeowner_id"]
    scopes = {ErasureScope(s) for s in req["scope"]}
    if ErasureScope.EVERYTHING in scopes:
        scopes = {
            ErasureScope.RECORDINGS,
            ErasureScope.TRANSCRIPTS,
            ErasureScope.VOICE_PROFILE,
        }

    db[COLL_ERASURE_REQUESTS].update_one(
        {"_id": req["_id"]}, {"$set": {"status": "executing"}}
    )

    counts: dict[str, int] = {}
    if ErasureScope.RECORDINGS in scopes:
        counts["recordings"] = _crypto_erase(
            db[COLL_RECORDINGS], homeowner_id, "recording", AuditAction.RECORDING_DELETED
        )
    if ErasureScope.TRANSCRIPTS in scopes:
        counts["transcripts"] = _crypto_erase(
            db[COLL_TRANSCRIPTS], homeowner_id, "transcript", AuditAction.TRANSCRIPT_DELETED
        )
    if ErasureScope.VOICE_PROFILE in scopes:
        result = db[COLL_VOICE_PROFILES].update_many(
            {"homeowner_id": homeowner_id, "deleted_at": None},
            {"$set": {"deleted_at": datetime.now(timezone.utc)}, "$unset": {"fingerprint_hash": ""}},
        )
        counts["voice_profiles"] = result.modified_count
        audit.append(
            homeowner_id=homeowner_id,
            actor="system:erasure",
            action=AuditAction.VOICE_PROFILE_DELETED,
            metadata={"request_id": req["request_id"]},
        )

    # Revoke emergency contact relay consent (we will no longer call them).
    if ErasureScope.EVERYTHING in {ErasureScope(s) for s in req["scope"]}:
        db[COLL_EMERGENCY_CONTACTS].update_many(
            {"homeowner_id": homeowner_id, "revoked_at": None},
            {"$set": {"revoked_at": datetime.now(timezone.utc)}},
        )

    db[COLL_ERASURE_REQUESTS].update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)}},
    )
    audit.append(
        homeowner_id=homeowner_id,
        actor="system:erasure",
        action=AuditAction.ERASURE_EXECUTED,
        metadata={"request_id": req["request_id"], "counts": counts},
    )
    log.info("erasure executed homeowner=%s counts=%s", homeowner_id, counts)


def _crypto_erase(
    coll: Any, homeowner_id: str, resource_type: str, action: AuditAction
) -> int:
    """Mark deleted + drop wrapped DEK + R2 object key. One audit entry per row
    so the homeowner gets a complete record."""
    now = datetime.now(timezone.utc)
    rows = list(
        coll.find(
            {"homeowner_id": homeowner_id, "deleted_at": None},
            projection={"_id": 1, resource_type + "_id": 1},
        )
    )
    for row in rows:
        coll.update_one(
            {"_id": row["_id"]},
            {"$set": {"deleted_at": now}, "$unset": {"dek_wrapped_b64": "", "encrypted_object_key": ""}},
        )
        audit.append(
            homeowner_id=homeowner_id,
            actor="system:erasure",
            action=action,
            resource_type=resource_type,
            resource_id=str(row.get(resource_type + "_id") or row["_id"]),
            metadata={"reason": "erasure_request"},
        )
    return len(rows)
