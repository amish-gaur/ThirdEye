"""Step 4b: outbound Twilio call that plays an ElevenLabs MP3.

Synthesizes the MP3, drops it in MEDIA_DIR (served by the FastAPI service),
then triggers a Twilio outbound call with TwiML <Play>.

Requires the FastAPI service to be running AND PUBLIC_BASE_URL to be reachable
from Twilio (use ngrok). For local dry-run, set DRY_RUN=true in .env.
"""

from __future__ import annotations

import argparse

from action_router.config import CONFIG
from action_router.tts import synthesize_mp3
from action_router.voice import place_call_play


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=CONFIG.homeowner_phone, help="E.164 phone number")
    parser.add_argument("--text", required=True, help="Script for ElevenLabs to speak")
    args = parser.parse_args()

    if not args.to:
        raise SystemExit("--to is required (or set HOMEOWNER_PHONE in .env)")

    mp3_path = synthesize_mp3(args.text)
    media_url = CONFIG.media_url(mp3_path.name)
    print(f"Synthesized -> {mp3_path}")
    print(f"Public URL  -> {media_url}")
    if media_url.startswith("http://127.") or media_url.startswith("http://localhost"):
        print("WARNING: PUBLIC_BASE_URL is local — Twilio cannot fetch this. Use ngrok.")

    result = place_call_play(args.to, media_url, fallback_text=args.text)
    print(f"sid={result.sid} to={result.to} dry_run={result.dry_run}")


if __name__ == "__main__":
    main()
