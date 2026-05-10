"""Smoke-test the iMessage fan-out in isolation (no Twilio, no vision).

    python -m scripts.test_imessage --to +16504839625
    python -m scripts.test_imessage --to +16504839625 --attach ./media/clip_xxx.mp4
    python -m scripts.test_imessage  # uses IMESSAGE_RECIPIENTS from .env

The first time you run this on a Mac, macOS will prompt:
    "Terminal/iTerm wants to control Messages.app. Allow?"
Click **Allow**. After that, sends are silent.
"""

from __future__ import annotations

import argparse
import logging
import sys

from action_router.config import CONFIG
from action_router.imessage import send_imessage_fanout


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--to",
        action="append",
        default=None,
        help="Recipient phone (E.164) or email. Repeat for multiple. "
        "Defaults to IMESSAGE_RECIPIENTS env.",
    )
    parser.add_argument(
        "--text",
        default="🔴 ThirdEye · T3 ALERT  ·  smoke test from scripts.test_imessage",
    )
    parser.add_argument("--attach", default=None, help="optional file path to attach")
    args = parser.parse_args()

    recipients = args.to or list(CONFIG.imessage_recipients)
    if not recipients:
        print(
            "ERROR: no recipients. Pass --to +1NNNNNNNNNN or set "
            "IMESSAGE_RECIPIENTS=+1...,+1... in .env",
            file=sys.stderr,
        )
        return 2

    print(f"Sending iMessage to {len(recipients)} recipient(s):")
    for r in recipients:
        print(f"  • {r}")

    results = send_imessage_fanout(recipients, args.text, attachment=args.attach)
    sent = sum(1 for r in results if r.sent)
    print(f"\n{sent}/{len(results)} sent")
    for r in results:
        flag = "✓" if r.sent else "✗"
        att = "  +clip" if r.attachment_sent else ""
        err = f"  ({r.error})" if r.error else ""
        print(f"  {flag} {r.to}{att}{err}")
    return 0 if sent == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
