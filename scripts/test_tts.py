"""Step 3b smoke test: synthesize one sentence to ./media/test.mp3."""

from __future__ import annotations

import argparse

from action_router.tts import synthesize_mp3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default="This is a SafeWatch test message.")
    parser.add_argument("--filename", default="test.mp3")
    args = parser.parse_args()

    path = synthesize_mp3(args.text, filename=args.filename)
    print(f"Wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
