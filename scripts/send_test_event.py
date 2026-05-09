"""POST a hardcoded event to the running action-router service for one tier."""

from __future__ import annotations

import argparse
import json

import requests

from action_router.config import CONFIG
from scripts._fixtures import sample_event


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, default=3, choices=[1, 2, 3, 4])
    parser.add_argument(
        "--url", default=f"http://127.0.0.1:{CONFIG.port}/event"
    )
    parser.add_argument(
        "--description",
        default="young man in a red hoodie and dark jeans",
        help="suspect_description as Qwen would emit it (clothing color required)",
    )
    parser.add_argument(
        "--summary",
        default="person picked up a package from the porch and walked away",
    )
    parser.add_argument(
        "--behavior",
        default=None,
        help="behavior_pattern (taking_item / loitering / fleeing / collapsed / ...)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.85,
        help="Qwen confidence in [0,1]. Below alert floor (0.55) downgrades the call.",
    )
    args = parser.parse_args()

    event = sample_event(
        tier=args.tier,
        description=args.description,
        summary=args.summary,
        confidence=args.confidence,
        behavior_pattern=args.behavior,
    )
    print(f"POST {args.url}\n{json.dumps(event, indent=2)}\n")
    resp = requests.post(args.url, json=event, timeout=15)
    print(f"-> {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)


if __name__ == "__main__":
    main()
