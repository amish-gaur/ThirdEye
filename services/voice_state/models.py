"""Pydantic models for voice-state operations.

These cross the lane boundary — Rishab's outbound code, my inbound code, and
the mobile API all consume them. Keep field names stable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class LegState(str, Enum):
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_ANSWER = "no-answer"
    FAILED = "failed"
    BUSY = "busy"


class IncidentVoiceState(str, Enum):
    OPEN = "open"  # at least one leg is ringing or answered
    ACKNOWLEDGED = "acknowledged"  # someone (homeowner/contact) accepted
    CANCELLED = "cancelled"  # explicitly cancelled by homeowner
    ESCALATED = "escalated"  # bumped to a higher tier mid-call
    RESOLVED = "resolved"  # all legs closed, no winner
    EXPIRED = "expired"  # TTL elapsed without a terminal state


class CallLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_sid: str
    incident_id: str
    homeowner_id: str
    direction: CallDirection
    target_label: str  # "homeowner" | "family" | "dispatch" | "neighbor:bob" | "inbound"
    target_phone: str | None = None
    state: LegState
    created_at: datetime
    updated_at: datetime
    answered_at: datetime | None = None
    ended_at: datetime | None = None


class IncidentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    homeowner_id: str
    state: IncidentVoiceState
    winner_call_sid: str | None = None
    legs: list[CallLeg] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---- HTTP API contracts ----------------------------------------------------


class RegisterLegRequest(BaseModel):
    incident_id: str
    homeowner_id: str
    call_sid: str
    direction: CallDirection
    target_label: str
    target_phone: str | None = None


class UpdateLegRequest(BaseModel):
    state: LegState
    reason: str | None = None


class WinnerRequest(BaseModel):
    """The leg whose owner accepted the call. Locks the incident to this leg
    and triggers cancellation of every other open leg."""

    call_sid: str


class CancelLegResponse(BaseModel):
    cancelled: bool
    twilio_hangup_attempted: bool


class WinnerResponse(BaseModel):
    accepted: bool  # False if a different winner already won
    winner_call_sid: str
    cancelled_legs: list[str]
