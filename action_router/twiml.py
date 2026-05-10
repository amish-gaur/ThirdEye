"""TwiML XML builders. Pure functions — easy to unit-test without Twilio."""

from __future__ import annotations

from xml.sax.saxutils import escape


def say_response(text: str, voice: str = "alice", language: str = "en-US") -> str:
    """`<Response><Say>...</Say></Response>` — simplest path, no media URL needed."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="{voice}" language="{language}">{escape(text)}</Say>'
        "</Response>"
    )


def say_with_gather(
    text: str,
    action_url: str,
    *,
    voice: str = "alice",
    language: str = "en-US",
    num_digits: int = 1,
) -> str:
    """Speak text, then collect DTMF digits for simple IVR decisions."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="{num_digits}" action="{escape(action_url)}" method="POST">'
        f'<Say voice="{voice}" language="{language}">{escape(text)}</Say>'
        "</Gather>"
        "<Hangup/>"
        "</Response>"
    )


def play_response(media_url: str, fallback_text: str | None = None) -> str:
    """`<Response><Play>URL</Play></Response>` — used after ElevenLabs synthesis.

    If `fallback_text` is provided, a `<Say>` is appended so the call still
    delivers the message if the MP3 fails to load.
    """
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<Response>",
        f"<Play>{escape(media_url)}</Play>",
    ]
    if fallback_text:
        parts.append(f'<Say voice="alice">{escape(fallback_text)}</Say>')
    parts.append("</Response>")
    return "".join(parts)


def play_with_gather(media_url: str, action_url: str, num_digits: int = 1) -> str:
    """Plays the MP3 then collects a single DTMF digit (used for Tier 3 IVR:
    press 1 to notify neighbors, 2 to ignore)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="{num_digits}" action="{escape(action_url)}" method="POST">'
        f"<Play>{escape(media_url)}</Play>"
        "</Gather>"
        "<Hangup/>"
        "</Response>"
    )
