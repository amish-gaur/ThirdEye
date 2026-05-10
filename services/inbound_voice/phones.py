"""Verified-phone directory.

When a homeowner verifies their phone (via onboarding/verification.py), we
upsert here. Inbound webhooks resolve caller-ID to homeowner via lookup.
Phones are stored as E.164.

Kept tiny and side-effect-only on purpose — the audit/consent state lives
elsewhere; this is just a lookup table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.database import Database

from .internal import mongo as mongo_mod

COLL_PHONES = "verified_phones"


def record_verified(*, homeowner_id: str, phone: str, db: Database | None = None) -> None:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_PHONES]
    now = datetime.now(timezone.utc)
    coll.update_one(
        {"phone": phone},
        {
            "$setOnInsert": {"created_at": now},
            "$set": {"homeowner_id": homeowner_id, "verified_at": now},
        },
        upsert=True,
    )


def lookup_homeowner(phone: str, *, db: Database | None = None) -> str | None:
    """Caller-ID resolution for inbound webhook. Returns None if unverified."""
    if not phone:
        return None
    coll = (db if db is not None else mongo_mod.get_db())[COLL_PHONES]
    doc = coll.find_one({"phone": phone, "verified_at": {"$ne": None}})
    return doc["homeowner_id"] if doc else None


def is_verified(*, homeowner_id: str, phone: str, db: Database | None = None) -> bool:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_PHONES]
    return bool(
        coll.find_one(
            {"homeowner_id": homeowner_id, "phone": phone, "verified_at": {"$ne": None}}
        )
    )
