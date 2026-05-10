"""Mongo client factory + collection accessors.

Sync pymongo client. We keep the surface tiny — each privacy/onboarding module
asks for the collection it needs, no shared abstract repository to maintain.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from ..config import CONFIG

log = logging.getLogger("inbound_voice.mongo")


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    client = MongoClient(CONFIG.mongo_uri, tz_aware=True)
    log.info("Mongo client created db=%s", CONFIG.mongo_db)
    return client


def get_db() -> Database:
    return get_client()[CONFIG.mongo_db]


def get_test_db() -> Any:
    """In-memory mongomock DB for unit tests."""
    import mongomock

    return mongomock.MongoClient(tz_aware=True)[CONFIG.mongo_db]


# Collection name constants — single source of truth so privacy + onboarding
# + retention all agree.
COLL_CONSENT = "consent_records"
COLL_VOICE_PROFILES = "voice_profiles"
COLL_VERIFICATIONS = "phone_verifications"
COLL_RECORDINGS = "call_recordings"
COLL_TRANSCRIPTS = "call_transcripts"
COLL_AUDIT = "privacy_audit_log"
COLL_ERASURE_REQUESTS = "erasure_requests"
COLL_HOMEOWNER_PRIVACY = "homeowner_privacy_settings"
COLL_EMERGENCY_CONTACTS = "emergency_contacts"


def collection(name: str, db: Database | None = None) -> Collection:
    return (db or get_db())[name]
