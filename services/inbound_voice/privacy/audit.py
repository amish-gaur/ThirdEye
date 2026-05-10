"""Append-only, hash-chained privacy audit log.

Every consent change, recording access, and erasure event lands here. The
chain hash makes silent tampering detectable: anyone can verify the chain
end-to-end by replaying SHA-256 over canonical entry payloads.

This is the source of truth we'd hand to a homeowner who asks "show me
everything you've done with my data."
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from ..internal import mongo as mongo_mod
from ..internal.mongo import COLL_AUDIT
from ..models import AuditAction, AuditLogEntry


def append(
    *,
    homeowner_id: str,
    actor: str,
    action: AuditAction,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    collection: Collection | None = None,
) -> AuditLogEntry:
    """Append an immutable, hash-chained entry. Returns the persisted entry."""
    coll = collection if collection is not None else _coll()
    last = _last_for_homeowner(coll, homeowner_id)
    seq = (last["seq"] + 1) if last else 1
    prev_hash = last["hash"] if last else ""

    # Store timestamp as ISO string in the document so the hash is stable
    # across backends (real Mongo rounds datetimes to ms; mongomock keeps
    # microsecond precision; serialization round-trips can shift tz info).
    ts_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "seq": seq,
        "homeowner_id": homeowner_id,
        "actor": actor,
        "action": action.value,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "metadata": metadata or {},
        "timestamp": ts_iso,
    }
    h = _chain_hash(prev_hash, payload)
    doc = {**payload, "prev_hash": prev_hash, "hash": h}
    coll.insert_one(doc)
    doc.pop("_id", None)
    return AuditLogEntry.model_validate(doc)


def verify_chain(
    *, homeowner_id: str, collection: Collection | None = None
) -> tuple[bool, int]:
    """Replay the chain. Returns (ok, count_verified). Stops at first mismatch."""
    coll = collection if collection is not None else _coll()
    cursor = coll.find({"homeowner_id": homeowner_id}).sort("seq", 1)
    prev_hash = ""
    count = 0
    for doc in cursor:
        payload = {k: doc[k] for k in (
            "seq", "homeowner_id", "actor", "action",
            "resource_type", "resource_id", "metadata", "timestamp",
        )}
        expected = _chain_hash(prev_hash, payload)
        if doc["prev_hash"] != prev_hash or doc["hash"] != expected:
            return False, count
        prev_hash = expected
        count += 1
    return True, count


# ---- internal ---------------------------------------------------------------


def _coll(db: Any = None) -> Collection:
    return (db or mongo_mod.get_db())[COLL_AUDIT]


def _last_for_homeowner(coll: Collection, homeowner_id: str) -> dict[str, Any] | None:
    return coll.find_one(
        {"homeowner_id": homeowner_id},
        sort=[("seq", -1)],
    )


def _chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    canonical = _canonical_json(payload)
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(b"\x00")
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


def _canonical_json(payload: dict[str, Any]) -> str:
    """Stable JSON: sorted keys, no NaN. Timestamps are pre-serialized to
    ISO strings by the caller — we don't accept naked datetimes here."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
