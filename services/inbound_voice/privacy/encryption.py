"""Envelope encryption for recordings + transcripts.

Threat model:
- A leaked Mongo dump must not yield plaintext recordings.
- A leaked R2/S3 bucket must not yield plaintext recordings.
- A compromised KMS master key must not retroactively decrypt: we accept this
  trade-off, but we plan for periodic master-key rotation (out of scope here).
- Cryptographic erasure: deleting the wrapped DEK row makes the ciphertext
  permanently unrecoverable, even if the bucket retains it (S3 retention,
  backups). This is what makes "delete my recording" actually safe.

Per-blob layout (object stored in R2):
  4 bytes magic 'SWE1'  | 12 bytes nonce | ciphertext+tag

Per-blob row in Mongo (`call_recordings.dek_wrapped_b64`):
  base64(KMS-wrapped 32-byte data key, AAD-bound to homeowner_id + recording_id)
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..internal.kms import KmsBackend, generate_data_key

MAGIC = b"SWE1"  # SafeWatch Encrypted v1
NONCE_LEN = 12


@dataclass(frozen=True)
class EncryptedBlob:
    ciphertext: bytes  # MAGIC + nonce + ciphertext||tag — what gets uploaded to R2
    dek_wrapped_b64: str  # what gets stored in Mongo

    @property
    def dek_wrapped(self) -> bytes:
        return base64.b64decode(self.dek_wrapped_b64)


def encrypt(
    *,
    plaintext: bytes,
    homeowner_id: str,
    resource_type: str,
    resource_id: str,
    kms: KmsBackend,
) -> EncryptedBlob:
    """Encrypt a payload (recording bytes / transcript text) with a fresh DEK.

    `homeowner_id`, `resource_type`, `resource_id` are bound into the DEK's
    KMS-wrap context. A wrapped DEK from one homeowner cannot be used to
    decrypt another homeowner's blob even if both ciphertexts are leaked.
    """
    if not homeowner_id or not resource_id:
        raise ValueError("homeowner_id and resource_id are required for AAD binding")

    dek = generate_data_key()
    context = _context(homeowner_id, resource_type, resource_id)
    wrapped = kms.wrap_data_key(dek, context)

    nonce = os.urandom(NONCE_LEN)
    ct_and_tag = AESGCM(dek).encrypt(nonce, plaintext, _aad(homeowner_id, resource_id))
    blob = MAGIC + nonce + ct_and_tag

    # Best-effort scrub of the DEK from memory.
    dek = b"\x00" * 32  # noqa: F841
    return EncryptedBlob(
        ciphertext=blob, dek_wrapped_b64=base64.b64encode(wrapped).decode("ascii")
    )


def decrypt(
    *,
    blob: bytes,
    dek_wrapped_b64: str,
    homeowner_id: str,
    resource_type: str,
    resource_id: str,
    kms: KmsBackend,
) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not a SafeWatch encrypted blob")
    body = blob[len(MAGIC):]
    if len(body) < NONCE_LEN + 16:
        raise ValueError("blob too short")
    nonce, ct_and_tag = body[:NONCE_LEN], body[NONCE_LEN:]

    wrapped = base64.b64decode(dek_wrapped_b64)
    context = _context(homeowner_id, resource_type, resource_id)
    dek = kms.unwrap_data_key(wrapped, context)

    try:
        plaintext = AESGCM(dek).decrypt(nonce, ct_and_tag, _aad(homeowner_id, resource_id))
    finally:
        dek = b"\x00" * 32  # noqa: F841
    return plaintext


def _context(homeowner_id: str, resource_type: str, resource_id: str) -> dict[str, str]:
    return {
        "h": homeowner_id,
        "rt": resource_type,
        "rid": resource_id,
        "v": "1",
    }


def _aad(homeowner_id: str, resource_id: str) -> bytes:
    """Bind ciphertext to homeowner + resource at the AES-GCM layer too."""
    return f"{homeowner_id}|{resource_id}".encode("utf-8")
