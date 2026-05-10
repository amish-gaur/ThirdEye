"""TwiML builders scoped to inbound flows.

Lives in this lane's namespace (not action_router/twiml.py) so the outbound
voice lane can evolve independently. If outbound code wants to use these
helpers it can import from here.
"""

from __future__ import annotations

from xml.sax.saxutils import escape


def say_response(text: str, *, voice: str = "alice", language: str = "en-US") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Say voice=\"{voice}\" language=\"{language}\">{escape(text)}</Say></Response>"
    )


def say_hangup(text: str, *, voice: str = "alice", language: str = "en-US") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response>"
        f'<Say voice="{voice}" language="{language}">{escape(text)}</Say>'
        f"<Hangup/>"
        f"</Response>"
    )


def say_then_gather(
    prompt: str,
    action_url: str,
    *,
    num_digits: int = 1,
    voice: str = "alice",
    language: str = "en-US",
    timeout_seconds: int = 6,
) -> str:
    """Speak `prompt`, then collect DTMF digits and POST to `action_url`.

    A trailing `<Say>+<Hangup>` covers the "no input" case so the call ends
    cleanly instead of timing out.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="{num_digits}" action="{escape(action_url)}" '
        f'method="POST" timeout="{timeout_seconds}">'
        f'<Say voice="{voice}" language="{language}">{escape(prompt)}</Say>'
        "</Gather>"
        f'<Say voice="{voice}" language="{language}">No input received. Goodbye.</Say>'
        "<Hangup/>"
        "</Response>"
    )
