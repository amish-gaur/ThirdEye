"""Mock concurrent blast: 4 Twilio voice calls + 4 iMessages, fired
simultaneously. Bypasses the action_router escalation logic so we can
isolate the "blast radius" feel of an emergency-tier event before wiring
this to the live theft pipeline.

Architecture::

    t=0   ┌─ thread A: 4 parallel Twilio API POSTs (each a 4th sub-thread)
          │   • each call fetches the same ElevenLabs MP3 from ngrok
          │   • placed-with-Twilio in ~0.4s; phones ring 3-5s later
          │
          └─ thread B: send_imessage_fanout (sequential per recipient)
              • Apple's AppleScript bridge drops parallel sends, so this
                MUST stay sequential — but the THREAD runs alongside A
              • ~0.6s per recipient → ~2.5s for 4

    wall-clock = max(A, B) ≈ 2.5-3s for all 8 things to be in flight.

Clip attachment is intentionally NOT included here — we add that in a
separate iteration once this baseline blast is proven.

Usage::

    python -m scripts.test_concurrent_calls
    python -m scripts.test_concurrent_calls --message "..."
    python -m scripts.test_concurrent_calls --to +16504839625 --to +14079214601
    python -m scripts.test_concurrent_calls --calls-only
    python -m scripts.test_concurrent_calls --imessage-only

Requires the action_router service to be up (it serves /media/<file>.mp3 to
Twilio over the public ngrok URL configured in PUBLIC_BASE_URL). iMessage
runs entirely locally via macOS Messages.app — no network from this side.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from action_router.config import CONFIG
from action_router.imessage import send_imessage_fanout
from action_router.tts import synthesize_mp3

log = logging.getLogger("scripts.test_concurrent_calls")


# (phone, label) — label is just for the printout so you can match SIDs to humans.
# Same roster is used for both the voice fan-out and the iMessage fan-out so
# every demo phone gets BOTH a ring and a text.
DEFAULT_ROSTER: List[Tuple[str, str]] = [
    ("+16504839625", "Aditya iPhone"),
    ("+14079214601", "Teammate A"),
    ("+15103580067", "Teammate B"),
    ("+15104581848", "Teammate C"),
]


DEFAULT_MESSAGE = (
    "This is ThirdEye Security calling about an incident at your home. "
    "At two forty seven A M, our cameras detected a package being taken "
    "from your front porch. The suspect was a tall man in a red hoodie "
    "and dark jeans. Authorities have been notified. "
    "Stay on the line for the security team."
)


# What the iMessage looks like. Mirrors action_router._format_imessage_body so
# the test feels representative of what the live pipeline will send. Single
# line, severity badge first, all the facts a homeowner needs to glance at.
DEFAULT_IMESSAGE_TEXT = (
    "🔴 ThirdEye · T4 EMERGENCY  ·  "
    "person picking up the package and walking away  ·  "
    "on the front porch  ·  "
    "(tall man in red hoodie and dark jeans)  ·  "
    "confidence 92%"
)


def _place_call(client, from_: str, to: str, twiml: str, label: str):
    try:
        call = client.calls.create(to=to, from_=from_, twiml=twiml)
        return (label, to, call.sid, None)
    except Exception as exc:  # noqa: BLE001
        return (label, to, None, str(exc)[:240])


_TERMINAL_FAILURE_STATUSES = {"failed", "no-answer", "busy", "canceled"}


def _fan_out_calls(roster: List[Tuple[str, str]], from_: str, twiml: str, sid: str, token: str):
    """Place every call in parallel and return list of (label, to, sid, err) tuples."""
    from twilio.rest import Client

    client = Client(sid, token)
    with ThreadPoolExecutor(max_workers=max(len(roster), 1)) as ex:
        futures = [
            ex.submit(_place_call, client, from_, phone, twiml, label)
            for phone, label in roster
        ]
        return [f.result() for f in as_completed(futures)]


def _retry_failed_calls(
    initial_results,
    from_: str,
    twiml: str,
    sid_creds: str,
    token: str,
    *,
    settle_seconds: float = 7.0,
) -> list:
    """One-shot retry for any call that didn't connect.

    Twilio occasionally drops one of N parallel calls from a brand-new account
    (random which one — looks like new-account anti-spam routing). After the
    initial burst, sleep `settle_seconds`, query the call status for every SID,
    and re-dial any that ended up in a terminal-failure state. Returns the
    same shape as _fan_out_calls() — one tuple per number, with the LATER
    attempt's SID/error if a retry happened.
    """
    from twilio.rest import Client

    client = Client(sid_creds, token)

    time.sleep(settle_seconds)

    final = []
    retries: list = []  # list of (label, to) to retry
    sid_by_to = {to: (label, call_sid, err) for (label, to, call_sid, err) in initial_results}

    for label, to, call_sid, err in initial_results:
        if not call_sid:
            # Twilio API rejected the create() outright — retry the create itself.
            retries.append((label, to))
            continue
        try:
            status = client.calls(call_sid).fetch().status
        except Exception:  # noqa: BLE001
            status = "unknown"
        if status in _TERMINAL_FAILURE_STATUSES:
            retries.append((label, to))
        else:
            final.append((label, to, call_sid, err))

    if retries:
        print(f"   ↻ retrying {len(retries)} dropped: {[t for _, t in retries]}")
        with ThreadPoolExecutor(max_workers=max(len(retries), 1)) as ex:
            retry_futures = [
                ex.submit(_place_call, client, from_, phone, twiml, label)
                for label, phone in retries
            ]
            for f in as_completed(retry_futures):
                final.append(f.result())

    return final


def _fan_out_imessages(roster: List[Tuple[str, str]], text: str):
    """Sequential per-recipient (Apple's bridge mandates this), but called from
    a sibling thread so it runs alongside the voice fan-out."""
    numbers = [phone for phone, _ in roster]
    return send_imessage_fanout(numbers, text, attachment=None)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default=DEFAULT_MESSAGE,
                        help="Voice script ElevenLabs reads aloud on each call.")
    parser.add_argument("--text", default=DEFAULT_IMESSAGE_TEXT,
                        help="iMessage body sent to every recipient.")
    parser.add_argument(
        "--to",
        action="append",
        default=None,
        help="Repeat to override the roster, e.g. --to +1... --to +1...",
    )
    parser.add_argument("--calls-only", action="store_true",
                        help="Skip iMessage fan-out (voice calls only).")
    parser.add_argument("--imessage-only", action="store_true",
                        help="Skip Twilio calls (iMessage fan-out only).")
    parser.add_argument("--no-retry", action="store_true",
                        help="Skip the auto-retry pass for dropped calls.")
    args = parser.parse_args()

    cfg = CONFIG

    do_calls = not args.imessage_only
    do_imessage = not args.calls_only

    if do_calls and not cfg.public_webhook_enabled():
        print(
            f"ERROR: PUBLIC_BASE_URL must be reachable from the internet so "
            f"Twilio can fetch the MP3. Got: {cfg.public_base_url}\n"
            f"Start ngrok: `ngrok http 8001` then restart the action_router "
            f"with PUBLIC_BASE_URL=<the https URL>.",
            file=sys.stderr,
        )
        return 2

    if do_calls and not (cfg.twilio_account_sid and cfg.twilio_auth_token and cfg.twilio_from_number):
        print("ERROR: Twilio creds incomplete in .env.", file=sys.stderr)
        return 2

    roster: List[Tuple[str, str]]
    if args.to:
        roster = [(p, p) for p in args.to]
    else:
        roster = DEFAULT_ROSTER

    twiml: str = ""
    mp3_url: str = ""
    if do_calls:
        # Synthesize the narration once. All 4 calls fetch the same MP3.
        print(f"Synthesizing narration via ElevenLabs (voice {cfg.elevenlabs_voice_id})...")
        mp3_path = synthesize_mp3(args.message, filename=f"concurrent_{int(time.time())}.mp3")
        print(f"  wrote {mp3_path} ({mp3_path.stat().st_size} bytes)")
        mp3_url = cfg.media_url(mp3_path.name)
        print(f"  Twilio will fetch from: {mp3_url}")

        # Inline TwiML — one Play + a one-second pause + Hangup. Twilio fetches
        # the MP3 over the ngrok tunnel; no TwiML webhook URL needed.
        twiml = (
            f"<Response>"
            f"<Play>{mp3_url}</Play>"
            f'<Pause length="1"/>'
            f"<Hangup/>"
            f"</Response>"
        )

    print()
    if do_calls and do_imessage:
        print(f"⚡ Blasting {len(roster)} calls AND {len(roster)} iMessages "
              f"in parallel (calls from {cfg.twilio_from_number})...")
    elif do_calls:
        print(f"⚡ Blasting {len(roster)} parallel calls from {cfg.twilio_from_number}...")
    else:
        print(f"⚡ Sending {len(roster)} iMessages (sequential per Apple)...")
    print()

    # Fire both halves at once. Top-level ThreadPoolExecutor with 2 workers:
    # one runs the call fan-out (which itself spawns 4 sub-threads), the other
    # runs the iMessage fan-out (sequential per recipient inside one thread).
    # Total wall-clock = max(call-time ~0.4s, imessage-time ~3s).
    t0 = time.time()
    call_results = []
    imessage_results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        future_calls = ex.submit(
            _fan_out_calls,
            roster,
            cfg.twilio_from_number,
            twiml,
            cfg.twilio_account_sid,
            cfg.twilio_auth_token,
        ) if do_calls else None
        future_imessage = ex.submit(_fan_out_imessages, roster, args.text) if do_imessage else None

        if future_calls is not None:
            call_results = future_calls.result()
        if future_imessage is not None:
            imessage_results = future_imessage.result()

    initial_dispatch_seconds = time.time() - t0

    # Auto-retry sweep for any dropped call. The initial dispatch might say
    # "queued" successfully but Twilio's edge can still drop one of N parallel
    # outbound calls from a young account. Wait a few seconds, query each
    # SID, and re-dial any that landed in a terminal-failure state.
    if do_calls and not args.no_retry:
        call_results = _retry_failed_calls(
            call_results,
            cfg.twilio_from_number,
            twiml,
            cfg.twilio_account_sid,
            cfg.twilio_auth_token,
        )

    dt = time.time() - t0

    # Calls report
    call_ok = 0
    if do_calls:
        print(f"📞 Calls placed (initial dispatch {initial_dispatch_seconds:.2f}s, total {dt:.2f}s with retries)")
        for label, to, sid, err in call_results:
            if sid:
                print(f"   ✓ {label:<18} {to:<14} sid={sid}")
                call_ok += 1
            else:
                print(f"   ✗ {label:<18} {to:<14} ERROR: {err}")
        print()

    # iMessage report
    msg_ok = 0
    if do_imessage:
        print(f"💬 iMessages sent")
        # imessage_results is a list of IMessageResult; ordering matches roster.
        roster_by_phone = {p: lbl for p, lbl in roster}
        for r in imessage_results:
            label = roster_by_phone.get(r.to, r.to)
            if r.sent:
                print(f"   ✓ {label:<18} {r.to}")
                msg_ok += 1
            else:
                print(f"   ✗ {label:<18} {r.to} ERROR: {r.error}")
        print()

    total_attempted = (len(call_results) if do_calls else 0) + (len(imessage_results) if do_imessage else 0)
    total_ok = call_ok + msg_ok
    print(
        f"{total_ok}/{total_attempted} delivered in {dt:.2f}s. "
        f"Phones should ring within ~3-5s; iMessages already on-screen."
    )
    return 0 if total_ok == total_attempted else 1


if __name__ == "__main__":
    sys.exit(main())
