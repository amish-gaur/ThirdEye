"""Per-homeowner retention enforcement.

Default 30 days. Each recording + transcript carries a `retain_until`. A
periodic sweep deletes expired rows AND the wrapped DEK — making the
ciphertext in R2 cryptographically unrecoverable even if the bucket retains
the object (cryptographic erasure).

We also fire `RECORDING_DELETED` / `TRANSCRIPT_DELETED` audit entries.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo.database import Database

from ..internal import mongo as mongo_mod
from ..internal.mongo import (
    COLL_HOMEOWNER_PRIVACY,
    COLL_RECORDINGS,
    COLL_TRANSCRIPTS,
)
from ..models import AuditAction
from . import audit

log = logging.getLogger("inbound_voice.privacy.retention")


def compute_retain_until(
    homeowner_id: str, *, default_days: int, db: Database | None = None
) -> datetime:
    """Look up the homeowner's retention preference; fall back to default."""
    settings = _privacy_settings(homeowner_id, db=db)
    days = int(settings.get("retention_days") or default_days)
    days = max(1, min(days, 365))
    return datetime.now(timezone.utc) + _days(days)


def sweep_expired(*, db: Database | None = None) -> dict[str, int]:
    """Delete every recording / transcript past its `retain_until`.

    Returns counts: `{"recordings": n, "transcripts": m}`.
    Cryptographic erasure: we delete the wrapped DEK; ciphertext in R2 is
    then unrecoverable. R2 object cleanup is the caller's responsibility
    (a separate scheduled job — kept here for tested correctness).
    """
    database = db if db is not None else mongo_mod.get_db()
    now = datetime.now(timezone.utc)

    rec_count = _sweep(
        database[COLL_RECORDINGS],
        now,
        homeowner_field="homeowner_id",
        resource_type="recording",
        action=AuditAction.RECORDING_DELETED,
    )
    tx_count = _sweep(
        database[COLL_TRANSCRIPTS],
        now,
        homeowner_field="homeowner_id",
        resource_type="transcript",
        action=AuditAction.TRANSCRIPT_DELETED,
    )
    log.info("retention sweep: %d recordings, %d transcripts deleted", rec_count, tx_count)
    return {"recordings": rec_count, "transcripts": tx_count}


# ---- internal ---------------------------------------------------------------


def _sweep(
    coll: Any,
    now: datetime,
    *,
    homeowner_field: str,
    resource_type: str,
    action: AuditAction,
) -> int:
    expired = list(
        coll.find(
            {"retain_until": {"$lte": now}, "deleted_at": None},
            projection={"_id": 1, homeowner_field: 1, resource_type + "_id": 1},
        )
    )
    n = 0
    for doc in expired:
        # Cryptographic erasure: drop the wrapped DEK + R2 object key.
        coll.update_one(
            {"_id": doc["_id"]},
            {"$set": {"deleted_at": now}, "$unset": {"dek_wrapped_b64": "", "encrypted_object_key": ""}},
        )
        audit.append(
            homeowner_id=doc[homeowner_field],
            actor="system:retention",
            action=action,
            resource_type=resource_type,
            resource_id=str(doc.get(resource_type + "_id") or doc["_id"]),
            metadata={"reason": "retention_window_expired"},
        )
        n += 1
    return n


def _privacy_settings(homeowner_id: str, *, db: Database | None = None) -> dict[str, Any]:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_HOMEOWNER_PRIVACY]
    return coll.find_one({"homeowner_id": homeowner_id}) or {}


def _days(n: int) -> Any:
    from datetime import timedelta

    return timedelta(days=n)
