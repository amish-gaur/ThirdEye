"""Step 3a smoke test: print the Claude-generated script for a tier."""

from __future__ import annotations

import argparse

from action_router.narration import generate_script
from scripts._fixtures import sample_event


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, default=3, choices=[1, 2, 3, 4])
    parser.add_argument("--description", default="person in red hoodie")
    parser.add_argument("--summary", default="took a package from the porch")
    args = parser.parse_args()

    event = sample_event(tier=args.tier, description=args.description, summary=args.summary)
    script = generate_script(event)
    print(f"Tier {args.tier} script:\n  {script!r}")


if __name__ == "__main__":
    main()
