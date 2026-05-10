"""Send iMessage via macOS AppleScript.

Used by the action router to fan out a "theft happened" notification to the
homeowner + team alongside the Twilio voice call. iMessage is free, instant,
supports attaching the clip mp4, and bypasses A2P 10DLC SMS registration
entirely (carrier rule does not apply to Apple's network).

Requirements
------------
* Running on macOS with Messages.app signed into iMessage on your Apple ID.
* Recipients must be reachable on iMessage (iPhone users; emails registered
  to an Apple ID also work).
* Terminal/iTerm needs Automation permission to control Messages. macOS will
  prompt the first time `send_imessage()` runs — click **Allow**. To inspect
  later: System Settings → Privacy & Security → Automation → your terminal.

Quick test::

    python -m scripts.test_imessage --to +16504839625
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ._trace import trace, trace_exception

log = logging.getLogger("action_router.imessage")


@dataclass(frozen=True)
class IMessageResult:
    to: str
    sent: bool
    attachment_sent: bool = False
    error: str | None = None


def _osascript_escape(s: str) -> str:
    """Escape backslashes and double-quotes for AppleScript string literals."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _run_osascript(script: str, *, timeout_seconds: float) -> tuple[int, str]:
    proc = subprocess.run(
        ["osascript", "-e", script],
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stderr or proc.stdout or "").strip()


def send_imessage(
    to: str,
    text: str,
    *,
    attachment: str | Path | None = None,
    timeout_seconds: float = 10.0,
) -> IMessageResult:
    """Send a single iMessage to a phone number or email.

    `to`           — E.164 phone (`+15551234567`) or email registered to iCloud
    `text`         — message body (no length cap from iMessage's side)
    `attachment`   — optional path to file. Image/video shown inline.

    macOS Messages.app sends are local — no network from this process required
    beyond what Apple does internally.
    """
    if platform.system() != "Darwin":
        return IMessageResult(to=to, sent=False, error="iMessage only works on macOS")
    if not to.strip():
        return IMessageResult(to=to, sent=False, error="empty recipient")

    text_e = _osascript_escape(text)
    to_e = _osascript_escape(to)

    # Send the text first.
    text_script = "\n".join([
        'tell application "Messages"',
        "  set targetService to 1st service whose service type = iMessage",
        f'  set theBuddy to buddy "{to_e}" of targetService',
        f'  send "{text_e}" to theBuddy',
        "end tell",
    ])
    trace("OSASCRIPT_TEXT", level="STEP", to=to, chars=len(text))
    t0 = time.monotonic()
    try:
        rc, err = _run_osascript(text_script, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        trace("OSASCRIPT_TIMEOUT", level="ERR", to=to,
              elapsed_s=round(time.monotonic() - t0, 3),
              hint="osascript hung — Messages.app may need Automation permission. "
                   "System Settings → Privacy & Security → Automation.")
        return IMessageResult(to=to, sent=False, error="timeout sending text")
    except FileNotFoundError:
        trace("OSASCRIPT_MISSING", level="ERR", to=to,
              hint="osascript binary not found — only macOS supports iMessage fan-out")
        return IMessageResult(to=to, sent=False, error="osascript not on PATH")

    if rc != 0:
        log.warning("iMessage text to %s failed (%d): %s", to, rc, err[:200])
        trace("OSASCRIPT_ERR", level="ERR", to=to, returncode=rc, stderr=err[:300],
              elapsed_s=round(time.monotonic() - t0, 3))
        return IMessageResult(to=to, sent=False, error=err[:200])

    log.info("iMessage text sent to %s (%d chars)", to, len(text))
    trace("OSASCRIPT_OK", level="OK", to=to, returncode=rc,
          elapsed_s=round(time.monotonic() - t0, 3))

    if not attachment:
        return IMessageResult(to=to, sent=True)

    # Send the attachment as a separate message — same chat thread.
    path = Path(attachment).expanduser().resolve()
    if not path.exists():
        log.warning("iMessage attachment %s missing; text-only delivered", path)
        trace("OSASCRIPT_ATTACH_MISSING", level="WARN", to=to, path=str(path))
        return IMessageResult(to=to, sent=True, error="attachment_missing")

    path_e = _osascript_escape(str(path))
    att_script = "\n".join([
        'tell application "Messages"',
        "  set targetService to 1st service whose service type = iMessage",
        f'  set theBuddy to buddy "{to_e}" of targetService',
        f'  send (POSIX file "{path_e}") to theBuddy',
        "end tell",
    ])
    trace("OSASCRIPT_ATTACH", level="STEP", to=to, path=str(path),
          size=path.stat().st_size)
    att_t0 = time.monotonic()
    try:
        rc, err = _run_osascript(att_script, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired:
        trace("OSASCRIPT_TIMEOUT", level="ERR", to=to, stage="attachment",
              elapsed_s=round(time.monotonic() - att_t0, 3))
        return IMessageResult(to=to, sent=True, error="timeout sending attachment")

    if rc != 0:
        log.warning("iMessage attachment to %s failed (%d): %s", to, rc, err[:200])
        trace("OSASCRIPT_ATTACH_ERR", level="ERR", to=to, returncode=rc,
              stderr=err[:300], elapsed_s=round(time.monotonic() - att_t0, 3))
        return IMessageResult(to=to, sent=True, attachment_sent=False, error=err[:200])

    log.info("iMessage attachment %s sent to %s", path.name, to)
    trace("OSASCRIPT_ATTACH_OK", level="OK", to=to, returncode=rc,
          elapsed_s=round(time.monotonic() - att_t0, 3))
    return IMessageResult(to=to, sent=True, attachment_sent=True)


def send_imessage_fanout(
    recipients: list[str] | tuple[str, ...],
    text: str,
    *,
    attachment: str | Path | None = None,
) -> list[IMessageResult]:
    """Send to every recipient sequentially.

    Sequential rather than parallel — Messages.app's AppleScript bridge
    occasionally drops sends when hammered concurrently. Each send is
    sub-second so 4 recipients = ~3 seconds total.
    """
    return [send_imessage(r, text, attachment=attachment) for r in recipients]
