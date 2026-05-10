"""Shared fixtures for inbound_voice tests.

We monkeypatch `get_db` and `get_redis` so every test runs against in-memory
backends. Real connections never happen in unit tests.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Ensure a deterministic master key for envelope-encryption tests before any
# module imports `services.inbound_voice.config`.
os.environ.setdefault(
    "SAFEWATCH_KMS_MASTER_KEY", "00112233445566778899aabbccddeeff" * 2
)


@pytest.fixture
def fake_db() -> Any:
    from services.inbound_voice.internal import mongo as mongo_mod

    db = mongo_mod.get_test_db()
    return db


@pytest.fixture(autouse=True)
def _patch_mongo(monkeypatch: pytest.MonkeyPatch, fake_db: Any) -> None:
    from services.inbound_voice.internal import mongo as mongo_mod

    monkeypatch.setattr(mongo_mod, "get_db", lambda: fake_db)


@pytest.fixture
def fake_redis() -> Any:
    from services.inbound_voice.internal import redis_client

    return redis_client.get_test_redis()


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch: pytest.MonkeyPatch, fake_redis: Any) -> None:
    from services.inbound_voice.internal import redis_client

    monkeypatch.setattr(redis_client, "get_redis", lambda: fake_redis)


@pytest.fixture
def kms() -> Any:
    from services.inbound_voice.internal.kms import SoftwareKms

    return SoftwareKms.from_env()
