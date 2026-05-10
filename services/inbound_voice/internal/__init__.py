"""Internal infrastructure clients.

This module contains thin wrappers around external services (Redis, Mongo,
Twilio, KMS). When `lane/live-query` lands `services/_shared/`, the canonical
versions of these will move there and this module will re-export from there.
"""
