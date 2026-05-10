"""Redis client factory with test-friendly fallback.

Sync redis-py is fine here — FastAPI can run sync code in a threadpool, and
Redis ops are sub-millisecond. We avoid the async client to keep the call
sites simple.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import redis

from ..config import CONFIG

log = logging.getLogger("inbound_voice.redis")


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    """Production Redis client, cached. Decode responses to str."""
    client = redis.Redis.from_url(CONFIG.redis_url, decode_responses=True)
    log.info("Redis client created url=%s", _redact_url(CONFIG.redis_url))
    return client


def get_test_redis() -> Any:
    """In-memory fakeredis for unit tests. Same interface as redis.Redis."""
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


def _redact_url(url: str) -> str:
    """Hide credentials in connection strings for logs."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    creds, _, host = rest.rpartition("@")
    if not creds:
        return url
    return f"{scheme}://***@{host}"
