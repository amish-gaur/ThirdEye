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
    parser.add_argument("--description", default="person in red hoodie")
    parser.add_argument("--summary", default="took a package from the porch")
    args = parser.parse_args()

    event = sample_event(tier=args.tier, description=args.description, summary=args.summary)
    print(f"POST {args.url}\n{json.dumps(event, indent=2)}\n")
    resp = requests.post(args.url, json=event, timeout=15)
    print(f"-> {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)


if __name__ == "__main__":
    main()
