"""KMS abstraction for envelope encryption.

Two backends:
  - SoftwareKMS: master key from env var, AES-256-GCM. For dev + tests.
  - AwsKms: real KMS via boto3 (lands when we deploy; not needed for the
    unit tests — they construct SoftwareKMS directly).

The contract is intentionally narrow: wrap/unwrap a 32-byte data key.
The encryption module owns the per-blob AES work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KmsBackend(Protocol):
    def wrap_data_key(self, plaintext_key: bytes, context: dict[str, str]) -> bytes: ...
    def unwrap_data_key(self, wrapped_key: bytes, context: dict[str, str]) -> bytes: ...


@dataclass(frozen=True)
class SoftwareKms:
    """Envelope encryption using a single master key from env.

    `context` is bound into the AAD so a wrapped key for homeowner A cannot be
    unwrapped under context for homeowner B even if the ciphertext leaks.
    """

    master_key: bytes  # 32 bytes

    @classmethod
    def from_hex(cls, hex_key: str) -> "SoftwareKms":
        raw = bytes.fromhex(hex_key)
        if len(raw) != 32:
            raise ValueError("master key must be 32 bytes (64 hex chars)")
        return cls(master_key=raw)

    @classmethod
    def from_env(cls, var: str = "SAFEWATCH_KMS_MASTER_KEY") -> "SoftwareKms":
        return cls.from_hex(os.environ[var])

    def wrap_data_key(self, plaintext_key: bytes, context: dict[str, str]) -> bytes:
        if len(plaintext_key) != 32:
            raise ValueError("data key must be 32 bytes")
        aad = _context_aad(context)
        nonce = os.urandom(12)
        ct = AESGCM(self.master_key).encrypt(nonce, plaintext_key, aad)
        return nonce + ct  # nonce || ciphertext||tag

    def unwrap_data_key(self, wrapped_key: bytes, context: dict[str, str]) -> bytes:
        if len(wrapped_key) < 12 + 16:
            raise ValueError("wrapped key too short")
        nonce, ct = wrapped_key[:12], wrapped_key[12:]
        aad = _context_aad(context)
        return AESGCM(self.master_key).decrypt(nonce, ct, aad)


def _context_aad(context: dict[str, str]) -> bytes:
    """Canonical encoding so the same context maps to the same AAD bytes."""
    if not context:
        return b""
    parts = sorted(context.items())
    return ("|".join(f"{k}={v}" for k, v in parts)).encode("utf-8")


def generate_data_key() -> bytes:
    """Fresh 256-bit data-encryption key."""
    return os.urandom(32)
