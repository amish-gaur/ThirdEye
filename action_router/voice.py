"""Step 4: Twilio outbound voice calls.

Two entry points:
    place_call_say(to, text)        - simple <Say>; Step 4a (no ElevenLabs needed)
    place_call_play(to, media_url)  - <Play> the ElevenLabs MP3; Step 4b
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .config import CONFIG, Config
from .twiml import play_response, say_response

log = logging.getLogger("action_router.voice")


@dataclass
class CallResult:
    sid: str
    to: str
    twiml: str
    dry_run: bool = False


def _client(config: Config):
    from twilio.rest import Client  # local import; SDK is heavy

    return Client(config.twilio_account_sid, config.twilio_auth_token)


def place_call_say(
    to: str,
    text: str,
    voice: str = "alice",
    config: Optional[Config] = None,
) -> CallResult:
    """Step 4a: outbound call that just speaks `text`. No media URL needed.

    Use this to validate Twilio creds + caller-ID before wiring ElevenLabs.
    """
    cfg = config or CONFIG
    twiml = say_response(text, voice=voice)
    if cfg.dry_run or not cfg.twilio_account_sid:
        log.warning("[DRY-RUN call→%s] %s", to, twiml)
        return CallResult(sid="DRYRUN", to=to, twiml=twiml, dry_run=True)
    call = _client(cfg).calls.create(to=to, from_=cfg.twilio_from_number, twiml=twiml)
    log.info("Twilio Say call placed sid=%s to=%s", call.sid, to)
    return CallResult(sid=call.sid, to=to, twiml=twiml)


def place_call_play(
    to: str,
    media_url: str,
    fallback_text: Optional[str] = None,
    config: Optional[Config] = None,
) -> CallResult:
    """Step 4b: outbound call that plays an MP3 (the ElevenLabs synthesis).

    `media_url` MUST be reachable from the public internet (use ngrok or
    similar in front of the FastAPI service).
    """
    cfg = config or CONFIG
    twiml = play_response(media_url, fallback_text=fallback_text)
    if cfg.dry_run or not cfg.twilio_account_sid:
        log.warning("[DRY-RUN call→%s] %s", to, twiml)
        return CallResult(sid="DRYRUN", to=to, twiml=twiml, dry_run=True)
    call = _client(cfg).calls.create(to=to, from_=cfg.twilio_from_number, twiml=twiml)
    log.info("Twilio Play call placed sid=%s to=%s media=%s", call.sid, to, media_url)
    return CallResult(sid=call.sid, to=to, twiml=twiml)
