"""Twilio client factory — wraps the SDK so tests can patch one place."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import CONFIG


@lru_cache(maxsize=1)
def get_client() -> Any:
    from twilio.rest import Client

    return Client(CONFIG.twilio_account_sid, CONFIG.twilio_auth_token)
