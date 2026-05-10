"""Step 4a: outbound Twilio call that just speaks `--text` via TwiML <Say>.

Use this to validate Twilio creds + caller-ID before wiring ElevenLabs.
"""

from __future__ import annotations

import argparse

from action_router.config import CONFIG
from action_router.voice import place_call_say


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=CONFIG.homeowner_phone, help="E.164 phone number")
    parser.add_argument("--text", default="This is a ThirdEye test call.")
    parser.add_argument("--voice", default="alice")
    args = parser.parse_args()

    if not args.to:
        raise SystemExit("--to is required (or set HOMEOWNER_PHONE in .env)")

    result = place_call_say(args.to, args.text, voice=args.voice)
    print(f"sid={result.sid} to={result.to} dry_run={result.dry_run}")
    print(f"twiml={result.twiml}")


if __name__ == "__main__":
    main()
