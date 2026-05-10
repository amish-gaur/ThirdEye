"""Step 4: Twilio outbound voice calls.

Two entry points:
    place_call_say(to, text)        - simple <Say>; Step 4a (no ElevenLabs needed)
    place_call_play(to, media_url)  - <Play> the ElevenLabs MP3; Step 4b

Person 2 hardening:
- Clamp `<Say>` text length so we never send a 4000+ char TwiML to Twilio.
- Single point of error handling so the router can surface Twilio failures
  without crashing the FastAPI request.
- Validate `to` looks like a phone number before calling Twilio.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .config import CONFIG, Config
from .twiml import play_response, play_with_gather, say_response, say_with_gather

log = logging.getLogger("action_router.voice")

# Twilio <Say> hard-caps around 4096 chars; we keep it well under for fast TTS.
SAY_TEXT_MAX_CHARS = 480
PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s().]{6,}$")


class VoiceError(RuntimeError):
    """Raised when a voice call cannot be placed (config / validation / Twilio)."""


@dataclass
class CallResult:
    sid: str
    to: str
    twiml: str
    dry_run: bool = False


def _client(config: Config):
    from twilio.rest import Client  # local import; SDK is heavy

    return Client(config.twilio_account_sid, config.twilio_auth_token)


def _validate_to(to: str) -> str:
    to = (to or "").strip()
    if not PHONE_RE.match(to):
        raise VoiceError(f"invalid phone number: {to!r}")
    return to


def _clamp_say(text: str) -> str:
    if not text:
        return "ThirdEye alert."
    cleaned = " ".join(text.split())
    if len(cleaned) <= SAY_TEXT_MAX_CHARS:
        return cleaned
    return cleaned[: SAY_TEXT_MAX_CHARS - 1].rstrip() + "."


def place_call_say(
    to: str,
    text: str,
    voice: str = "alice",
    gather_action_url: str | None = None,
    config: Optional[Config] = None,
) -> CallResult:
    """Step 4a: outbound call that just speaks `text`. No media URL needed."""
    cfg = config or CONFIG
    to = _validate_to(to)
    text = _clamp_say(text)
    twiml = (
        say_with_gather(text, gather_action_url, voice=voice)
        if gather_action_url
        else say_response(text, voice=voice)
    )

    if cfg.dry_run or not cfg.twilio_account_sid:
        log.warning("[DRY-RUN call→%s] %s", to, twiml)
        return CallResult(sid="DRYRUN", to=to, twiml=twiml, dry_run=True)

    try:
        call = _client(cfg).calls.create(
            to=to, from_=cfg.twilio_from_number, twiml=twiml
        )
    except Exception as exc:  # noqa: BLE001 — convert to one stable error type
        log.exception("Twilio Say call failed to=%s", to)
        raise VoiceError(f"twilio say failed: {exc}") from exc

    log.info("Twilio Say call placed sid=%s to=%s", call.sid, to)
    return CallResult(sid=call.sid, to=to, twiml=twiml)


def place_call_play(
    to: str,
    media_url: str,
    fallback_text: Optional[str] = None,
    gather_action_url: str | None = None,
    config: Optional[Config] = None,
) -> CallResult:
    """Step 4b: outbound call that plays an MP3 (the ElevenLabs synthesis).

    `media_url` MUST be reachable from the public internet (use ngrok or
    similar in front of the FastAPI service).
    """
    cfg = config or CONFIG
    to = _validate_to(to)

    if not media_url or not media_url.lower().startswith(("http://", "https://")):
        raise VoiceError(f"invalid media_url: {media_url!r}")

    fallback = _clamp_say(fallback_text) if fallback_text else None
    twiml = (
        play_with_gather(media_url, gather_action_url)
        if gather_action_url
        else play_response(media_url, fallback_text=fallback)
    )

    if cfg.dry_run or not cfg.twilio_account_sid:
        log.warning("[DRY-RUN call→%s] %s", to, twiml)
        return CallResult(sid="DRYRUN", to=to, twiml=twiml, dry_run=True)

    try:
        call = _client(cfg).calls.create(
            to=to, from_=cfg.twilio_from_number, twiml=twiml
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Twilio Play call failed to=%s media=%s", to, media_url)
        raise VoiceError(f"twilio play failed: {exc}") from exc

    log.info("Twilio Play call placed sid=%s to=%s media=%s", call.sid, to, media_url)
    return CallResult(sid=call.sid, to=to, twiml=twiml)
