"""Publish a synthetic active-incident to voice_state for demo / smoke tests.

Use this when the action_router hook isn't wired up yet but you want the
inbound IVR to behave as if a real tier-3 event just fired:

    python -m scripts.publish_active_incident \
        --homeowner-id hwn_alice \
        --incident-id inc_demo \
        --tier 3 \
        --summary "person reaching toward porch package" \
        --scene "the front porch"

Then dial the SafeWatch number (with a phone whose verified-phone row points
to `hwn_alice`) and the inbound webhook will play the active-incident IVR.
"""

from __future__ import annotations

import argparse
import sys

from services.voice_state import cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homeowner-id", required=True)
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--tier", type=int, default=3, choices=[3, 4])
    parser.add_argument("--summary", default="activity at your home")
    parser.add_argument("--scene", default="")
    parser.add_argument("--behavior", default="taking_item")
    parser.add_argument("--ttl-seconds", type=int, default=300)
    args = parser.parse_args(argv)

    payload = {
        "incident_id": args.incident_id,
        "homeowner_id": args.homeowner_id,
        "tier": args.tier,
        "tier_name": "ALERT" if args.tier == 3 else "EMERGENCY",
        "one_line_summary": args.summary,
        "scene": args.scene,
        "behavior_pattern": args.behavior,
    }
    ok = cache.publish_active_incident(payload, ttl_seconds=args.ttl_seconds)
    if ok:
        print(
            f"published incident={args.incident_id} homeowner={args.homeowner_id} "
            f"tier={args.tier} ttl={args.ttl_seconds}s"
        )
        return 0
    print("FAILED to publish (check Redis is running and ids non-empty)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
