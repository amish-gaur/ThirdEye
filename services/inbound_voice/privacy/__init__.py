"""Privacy primitives for the phone-infra lane.

Public surface:
    encryption  — envelope encryption per homeowner (AES-256-GCM + KMS-wrapped DEK)
    redaction   — auto-redact PII from transcripts before persistence
    retention   — enforce per-homeowner retention windows; cryptographic erasure
    erasure     — right-to-erasure with grace period; cascades across modules
    audit       — append-only, hash-chained access log
"""

from . import audit, encryption, erasure, redaction, retention

__all__ = ["audit", "encryption", "erasure", "redaction", "retention"]
