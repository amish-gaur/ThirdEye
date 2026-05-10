from __future__ import annotations

import pytest

from services.inbound_voice.privacy.encryption import decrypt, encrypt


def test_round_trip(kms) -> None:
    plaintext = b"this is a test recording payload" * 100
    blob = encrypt(
        plaintext=plaintext,
        homeowner_id="hwn_alice",
        resource_type="recording",
        resource_id="rec_123",
        kms=kms,
    )
    out = decrypt(
        blob=blob.ciphertext,
        dek_wrapped_b64=blob.dek_wrapped_b64,
        homeowner_id="hwn_alice",
        resource_type="recording",
        resource_id="rec_123",
        kms=kms,
    )
    assert out == plaintext


def test_wrapped_dek_is_homeowner_bound(kms) -> None:
    """A DEK wrapped for homeowner A cannot be unwrapped under homeowner B's
    context. This is the property that makes leaked Mongo dumps useless."""
    plaintext = b"alice's secret"
    blob = encrypt(
        plaintext=plaintext,
        homeowner_id="hwn_alice",
        resource_type="recording",
        resource_id="rec_123",
        kms=kms,
    )
    with pytest.raises(Exception):
        decrypt(
            blob=blob.ciphertext,
            dek_wrapped_b64=blob.dek_wrapped_b64,
            homeowner_id="hwn_bob",  # WRONG homeowner
            resource_type="recording",
            resource_id="rec_123",
            kms=kms,
        )


def test_resource_type_binding(kms) -> None:
    blob = encrypt(
        plaintext=b"x",
        homeowner_id="h",
        resource_type="recording",
        resource_id="r",
        kms=kms,
    )
    with pytest.raises(Exception):
        decrypt(
            blob=blob.ciphertext,
            dek_wrapped_b64=blob.dek_wrapped_b64,
            homeowner_id="h",
            resource_type="transcript",  # WRONG type
            resource_id="r",
            kms=kms,
        )


def test_resource_id_binding(kms) -> None:
    blob = encrypt(
        plaintext=b"x",
        homeowner_id="h",
        resource_type="recording",
        resource_id="rec_1",
        kms=kms,
    )
    with pytest.raises(Exception):
        decrypt(
            blob=blob.ciphertext,
            dek_wrapped_b64=blob.dek_wrapped_b64,
            homeowner_id="h",
            resource_type="recording",
            resource_id="rec_2",  # WRONG resource id
            kms=kms,
        )


def test_distinct_invocations_produce_distinct_ciphertexts(kms) -> None:
    """Random DEK + random nonce: same plaintext should never produce the same
    ciphertext twice. Detects any nonce-reuse regression."""
    common = dict(
        plaintext=b"identical input",
        homeowner_id="h",
        resource_type="recording",
        resource_id="r",
        kms=kms,
    )
    a = encrypt(**common)
    b = encrypt(**common)
    assert a.ciphertext != b.ciphertext
    assert a.dek_wrapped_b64 != b.dek_wrapped_b64


def test_blob_starts_with_magic(kms) -> None:
    blob = encrypt(
        plaintext=b"x",
        homeowner_id="h",
        resource_type="recording",
        resource_id="r",
        kms=kms,
    )
    assert blob.ciphertext.startswith(b"SWE1")


def test_truncated_blob_rejected(kms) -> None:
    blob = encrypt(
        plaintext=b"hello",
        homeowner_id="h",
        resource_type="recording",
        resource_id="r",
        kms=kms,
    )
    with pytest.raises(ValueError):
        decrypt(
            blob=blob.ciphertext[:10],  # truncated
            dek_wrapped_b64=blob.dek_wrapped_b64,
            homeowner_id="h",
            resource_type="recording",
            resource_id="r",
            kms=kms,
        )
