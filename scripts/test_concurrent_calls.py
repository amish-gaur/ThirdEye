"""Mock concurrent-call test: synthesize one ElevenLabs narration, place
parallel Twilio calls to all four demo phones simultaneously.

Bypasses the action_router escalation logic — this is a *raw* call-placement
test so we can hear how the voice sounds and confirm 4 phones ring at once.
Once the voice + concurrency feel right, the same TwiML path is what the
router uses on a real T4 escalation from the Qwen pipeline.

Usage::

    python -m scripts.test_concurrent_calls
    python -m scripts.test_concurrent_calls --message "..."
    python -m scripts.test_concurrent_calls --to +16504839625 --to +14079214601

Requires the action_router service to be up (it serves /media/<file>.mp3 to
Twilio over the public ngrok URL configured in PUBLIC_BASE_URL).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from action_router.config import CONFIG
from action_router.tts import synthesize_mp3

log = logging.getLogger("scripts.test_concurrent_calls")


# (phone, label) — label is just for the printout so you can match SIDs to humans
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


def _place_call(client, from_: str, to: str, twiml: str, label: str):
    try:
        call = client.calls.create(to=to, from_=from_, twiml=twiml)
        return (label, to, call.sid, None)
    except Exception as exc:  # noqa: BLE001
        return (label, to, None, str(exc)[:240])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument(
        "--to",
        action="append",
        default=None,
        help="Repeat to override the roster, e.g. --to +1... --to +1...",
    )
    args = parser.parse_args()

    cfg = CONFIG

    if not cfg.public_webhook_enabled():
        print(
            f"ERROR: PUBLIC_BASE_URL must be reachable from the internet so "
            f"Twilio can fetch the MP3. Got: {cfg.public_base_url}\n"
            f"Start ngrok: `ngrok http 8001` then restart the action_router "
            f"with PUBLIC_BASE_URL=<the https URL>.",
            file=sys.stderr,
        )
        return 2

    if not (cfg.twilio_account_sid and cfg.twilio_auth_token and cfg.twilio_from_number):
        print("ERROR: Twilio creds incomplete in .env.", file=sys.stderr)
        return 2

    roster: List[Tuple[str, str]]
    if args.to:
        roster = [(p, p) for p in args.to]
    else:
        roster = DEFAULT_ROSTER

    # 1. Synthesize the narration once. All 4 calls fetch the same MP3.
    print(f"Synthesizing narration via ElevenLabs (voice {cfg.elevenlabs_voice_id})...")
    mp3_path = synthesize_mp3(args.message, filename=f"concurrent_{int(time.time())}.mp3")
    print(f"  wrote {mp3_path} ({mp3_path.stat().st_size} bytes)")

    mp3_url = cfg.media_url(mp3_path.name)
    print(f"  Twilio will fetch from: {mp3_url}")

    # 2. Build inline TwiML — one Play + a one-second pause + Hangup.
    # Twilio fetches the MP3 over the ngrok tunnel; no TwiML webhook URL needed.
    twiml = (
        f"<Response>"
        f"<Play>{mp3_url}</Play>"
        f'<Pause length="1"/>'
        f"<Hangup/>"
        f"</Response>"
    )

    # 3. Fire all calls in parallel. Each create() blocks until Twilio returns
    # the SID (~200ms); the actual ringing happens on Twilio's side after.
    from twilio.rest import Client

    client = Client(cfg.twilio_account_sid, cfg.twilio_auth_token)
    print(
        f"\nPlacing {len(roster)} parallel calls "
        f"from {cfg.twilio_from_number}...\n"
    )

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(roster)) as ex:
        futures = [
            ex.submit(_place_call, client, cfg.twilio_from_number, phone, twiml, label)
            for phone, label in roster
        ]
        results = [f.result() for f in as_completed(futures)]
    dt = time.time() - t0

    print(f"All {len(results)} calls placed with Twilio in {dt:.2f}s.\n")

    ok = 0
    for label, to, sid, err in results:
        if sid:
            print(f"  ✓ {label:<18} {to:<14} sid={sid}")
            ok += 1
        else:
            print(f"  ✗ {label:<18} {to:<14} ERROR: {err}")

    print(
        f"\n{ok}/{len(results)} queued — phones should ring within ~3-5s. "
        f"Twilio will <Play> the same MP3 on every call."
    )
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
