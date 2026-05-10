"""Onboarding for the phone-infra lane.

Public surface:
    verification — phone-number verification via Twilio Verify (or stub)
    consent      — typed consent state machine; ties into audit log
    voice_profile — voice biometric enrollment (fingerprint hash, never raw audio)
    emergency_contacts — invite + mutual-consent flow for relay-call contacts
    api          — FastAPI router exposing all of the above
"""

from . import consent, emergency_contacts, verification, voice_profile

__all__ = ["consent", "emergency_contacts", "verification", "voice_profile"]
