"""Pydantic models for the inbound-voice service.

These define the wire format for the onboarding and mobile APIs and the
storage shape for Mongo documents. Kept in one file so the lane is easy to
review and so TS export is mechanical.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# E.164 phone number — leading "+", 8-15 digits.
PhoneE164 = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{7,14}$")]


# ---- Consent ----------------------------------------------------------------


class ConsentType(str, Enum):
    RECORDING = "recording"  # we record inbound + outbound calls about this homeowner
    VOICE_BIOMETRIC = "voice_biometric"  # we store a voice fingerprint for caller-ID
    EMERGENCY_RELAY = "emergency_relay"  # we may call family / "dispatch" on their behalf
    AI_NARRATION = "ai_narration"  # we send event metadata to Anthropic for narration
    TRANSCRIPT_STORAGE = "transcript_storage"  # we store transcripts (redacted) for query


class ConsentState(str, Enum):
    GRANTED = "granted"
    REVOKED = "revoked"


class ConsentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    homeowner_id: str
    consent_type: ConsentType
    state: ConsentState
    jurisdiction: str  # ISO state code, e.g. "US-CA"; "US" if state unknown
    policy_version: str  # ties this consent to a specific privacy policy revision
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    source_ip: str | None = None
    user_agent: str | None = None


class ConsentRequest(BaseModel):
    consent_type: ConsentType
    state: ConsentState
    jurisdiction: str | None = None  # server fills from caller IP if missing


# ---- Onboarding -------------------------------------------------------------


class PhoneVerificationStart(BaseModel):
    phone: PhoneE164


class PhoneVerificationCheck(BaseModel):
    phone: PhoneE164
    code: Annotated[str, StringConstraints(pattern=r"^\d{4,8}$")]


class OnboardingStatus(BaseModel):
    homeowner_id: str
    phone_verified: bool
    consents_granted: list[ConsentType]
    voice_profile_enrolled: bool
    emergency_contacts: int
    completed: bool


# ---- Voice profile ----------------------------------------------------------


class VoiceProfileEnrollment(BaseModel):
    """We enroll a salted hash of the audio fingerprint, never the raw audio.

    The mobile app computes the fingerprint locally (mel-spec → small embedding)
    and uploads only the hash + a short ciphertext for verification challenges.
    """

    fingerprint_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    sample_count: int = Field(ge=1, le=10)


# ---- Emergency contacts (mutual consent — we will call them) ---------------


class EmergencyContactRole(str, Enum):
    FAMILY = "family"
    NEIGHBOR = "neighbor"
    DISPATCH = "dispatch"
    OTHER = "other"


class EmergencyContactInvite(BaseModel):
    role: EmergencyContactRole
    name: str
    phone: PhoneE164


class EmergencyContact(BaseModel):
    contact_id: str
    homeowner_id: str
    role: EmergencyContactRole
    name: str
    phone: PhoneE164
    invited_at: datetime
    consented_at: datetime | None = None
    revoked_at: datetime | None = None


# ---- Privacy settings -------------------------------------------------------


class HomeownerPrivacySettings(BaseModel):
    homeowner_id: str
    retention_days: int = Field(ge=1, le=365)
    allow_recording: bool = True
    allow_voice_biometric: bool = False  # opt-in
    allow_transcripts: bool = True
    jurisdiction_override: str | None = None


# ---- Recording / transcript metadata ---------------------------------------


class RecordingMetadata(BaseModel):
    recording_id: str
    homeowner_id: str
    call_sid: str
    incident_id: str | None
    direction: str  # "inbound" | "outbound"
    duration_seconds: float
    started_at: datetime
    ended_at: datetime
    encrypted_object_key: str
    dek_wrapped_b64: str
    retain_until: datetime
    deleted_at: datetime | None = None


class TranscriptMetadata(BaseModel):
    transcript_id: str
    recording_id: str
    homeowner_id: str
    encrypted_object_key: str
    dek_wrapped_b64: str
    redaction_count: int
    retain_until: datetime
    deleted_at: datetime | None = None


# ---- Erasure ----------------------------------------------------------------


class ErasureScope(str, Enum):
    RECORDINGS = "recordings"
    TRANSCRIPTS = "transcripts"
    VOICE_PROFILE = "voice_profile"
    EVERYTHING = "everything"


class ErasureRequest(BaseModel):
    request_id: str
    homeowner_id: str
    scope: list[ErasureScope]
    requested_at: datetime
    scheduled_for: datetime  # grace-period delete; user can cancel until then
    status: str  # "pending" | "executing" | "completed" | "cancelled"
    completed_at: datetime | None = None


# ---- Audit log --------------------------------------------------------------


class AuditAction(str, Enum):
    CONSENT_GRANTED = "consent_granted"
    CONSENT_REVOKED = "consent_revoked"
    RECORDING_ACCESSED = "recording_accessed"
    RECORDING_DELETED = "recording_deleted"
    TRANSCRIPT_ACCESSED = "transcript_accessed"
    TRANSCRIPT_DELETED = "transcript_deleted"
    VOICE_PROFILE_ENROLLED = "voice_profile_enrolled"
    VOICE_PROFILE_DELETED = "voice_profile_deleted"
    ERASURE_REQUESTED = "erasure_requested"
    ERASURE_EXECUTED = "erasure_executed"
    ERASURE_CANCELLED = "erasure_cancelled"
    PHONE_VERIFICATION_SENT = "phone_verification_sent"
    PHONE_VERIFICATION_SUCCEEDED = "phone_verification_succeeded"
    PHONE_VERIFICATION_FAILED = "phone_verification_failed"
    EMERGENCY_CONTACT_INVITED = "emergency_contact_invited"
    EMERGENCY_CONTACT_CONSENTED = "emergency_contact_consented"
    EMERGENCY_CONTACT_REVOKED = "emergency_contact_revoked"


class AuditLogEntry(BaseModel):
    seq: int  # monotonic per homeowner
    homeowner_id: str
    actor: str  # "homeowner" | "system" | "<staff:email>"
    action: AuditAction
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime
    prev_hash: str  # hex; "" for the first entry per homeowner
    hash: str  # hex; SHA-256(prev_hash || canonical(payload))
