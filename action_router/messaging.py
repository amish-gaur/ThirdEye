"""Twilio SMS for Tier 2 NOTICE (quiet text, no call)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from .config import CONFIG, Config

log = logging.getLogger("action_router.messaging")


@dataclass
class SmsResult:
    sid: str
    to: str
    body: str
    dry_run: bool = False


def send_sms(
    to: str,
    body: str,
    media_urls: Optional[Sequence[str]] = None,
    config: Optional[Config] = None,
) -> SmsResult:
    cfg = config or CONFIG
    if cfg.dry_run or not cfg.twilio_account_sid:
        log.warning("[DRY-RUN sms→%s] %s", to, body)
        return SmsResult(sid="DRYRUN", to=to, body=body, dry_run=True)

    from twilio.rest import Client

    client = Client(cfg.twilio_account_sid, cfg.twilio_auth_token)
    kwargs = {"to": to, "from_": cfg.twilio_from_number, "body": body}
    if media_urls:
        kwargs["media_url"] = list(media_urls)
    msg = client.messages.create(**kwargs)
    log.info("Twilio message sid=%s to=%s", msg.sid, to)
    return SmsResult(sid=msg.sid, to=to, body=body)
