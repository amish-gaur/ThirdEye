"""Emergency contacts: people SafeWatch may call on the homeowner's behalf.

We can't legally (or ethically) auto-call someone's family member without
that person's own consent — the homeowner can consent on their own behalf
but not for someone else. So:

1. Homeowner adds a contact (name, phone, role).
2. We send the contact a one-time SMS with a short consent token + link.
3. Contact taps "yes, SafeWatch may call me about <homeowner name> in
   emergencies" or just replies YES.
4. We mark `consented_at`. Until then, that contact is NOT in the call fan-out.
5. Either party can revoke at any time.

The contact's phone number is stored as plain E.164 (we need to dial it),
but never appears in any homeowner-facing transcript without their consent.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from pymongo.database import Database

from ..internal import mongo as mongo_mod
from ..internal.mongo import COLL_EMERGENCY_CONTACTS
from ..models import AuditAction, EmergencyContact, EmergencyContactRole
from ..privacy import audit

log = logging.getLogger("inbound_voice.onboarding.emergency_contacts")


def invite(
    *,
    homeowner_id: str,
    role: EmergencyContactRole,
    name: str,
    phone: str,
    db: Database | None = None,
) -> tuple[EmergencyContact, str]:
    """Add a contact in `pending` state. Returns (contact, consent_token).

    The caller is responsible for sending the actual SMS (so we can mock it
    in tests and gate on outbound rate limits in production).
    """
    coll = (db if db is not None else mongo_mod.get_db())[COLL_EMERGENCY_CONTACTS]
    now = datetime.now(timezone.utc)
    contact_id = f"con_{uuid.uuid4().hex[:12]}"
    consent_token = secrets.token_urlsafe(24)
    doc = {
        "contact_id": contact_id,
        "homeowner_id": homeowner_id,
        "role": role.value,
        "name": name,
        "phone": phone,
        "invited_at": now,
        "consented_at": None,
        "revoked_at": None,
        "consent_token_hash": _hash_token(consent_token),
    }
    coll.insert_one(dict(doc))
    audit.append(
        homeowner_id=homeowner_id,
        actor="homeowner",
        action=AuditAction.EMERGENCY_CONTACT_INVITED,
        resource_type="emergency_contact",
        resource_id=contact_id,
        metadata={"role": role.value},
    )
    doc.pop("consent_token_hash", None)
    return EmergencyContact.model_validate(doc), consent_token


def accept_invite(*, contact_id: str, consent_token: str, db: Database | None = None) -> bool:
    """Mutual-consent step. Returns True if accepted, False if token invalid
    or already accepted/revoked."""
    import hmac

    coll = (db if db is not None else mongo_mod.get_db())[COLL_EMERGENCY_CONTACTS]
    doc = coll.find_one({"contact_id": contact_id, "revoked_at": None})
    if not doc:
        return False
    expected_hash = doc.get("consent_token_hash") or ""
    if not hmac.compare_digest(expected_hash, _hash_token(consent_token)):
        return False
    if doc.get("consented_at"):
        return True  # idempotent: already accepted with this token
    coll.update_one(
        {"_id": doc["_id"]},
        {"$set": {"consented_at": datetime.now(timezone.utc)}},
    )
    audit.append(
        homeowner_id=doc["homeowner_id"],
        actor=f"contact:{contact_id}",
        action=AuditAction.EMERGENCY_CONTACT_CONSENTED,
        resource_type="emergency_contact",
        resource_id=contact_id,
    )
    return True


def revoke(*, contact_id: str, actor: str, db: Database | None = None) -> bool:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_EMERGENCY_CONTACTS]
    result = coll.update_one(
        {"contact_id": contact_id, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc)}},
    )
    if result.modified_count:
        doc = coll.find_one({"contact_id": contact_id}, projection={"homeowner_id": 1})
        if doc:
            audit.append(
                homeowner_id=doc["homeowner_id"],
                actor=actor,
                action=AuditAction.EMERGENCY_CONTACT_REVOKED,
                resource_type="emergency_contact",
                resource_id=contact_id,
            )
    return result.modified_count > 0


def list_active(*, homeowner_id: str, db: Database | None = None) -> list[EmergencyContact]:
    coll = (db if db is not None else mongo_mod.get_db())[COLL_EMERGENCY_CONTACTS]
    out: list[EmergencyContact] = []
    for doc in coll.find(
        {"homeowner_id": homeowner_id, "revoked_at": None, "consented_at": {"$ne": None}}
    ):
        doc.pop("_id", None)
        doc.pop("consent_token_hash", None)
        out.append(EmergencyContact.model_validate(doc))
    return out


def _hash_token(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
