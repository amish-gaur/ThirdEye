"""End-to-end smoke test for the cloud VLM backend.

Reads a real frame that previously triggered a Qwen emit, runs it
through the new ``CloudHeavyClassifier``, parses the response with the
existing ``vision_pipeline.events.evaluate_classifier_output``, and
prints what the engine would have built into a router event.

By default this hits the live Anthropic API (costs a fraction of a
cent and exercises the real wire format). Pass ``--offline`` to swap
in a fake client that returns a fixed JSON payload — useful when the
account is out of credits or you just want to verify wiring.

    python -m scripts.smoke_cloud_classifier              # live
    python -m scripts.smoke_cloud_classifier --offline    # mocked
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
from dotenv import load_dotenv

# Test tooling trusts .env > shell env, so a stale ANTHROPIC_API_KEY left
# in someone's zsh profile doesn't silently override what they just put
# in .env. Production config (vision_pipeline/config.py) keeps the
# default non-override behavior so shell exports still work in CI.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from vision_pipeline.cloud_classifier import CloudHeavyClassifier
from vision_pipeline.config import CONFIG
from vision_pipeline.events import VISION_LANGUAGE_PROMPT, evaluate_classifier_output


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FRAME = REPO_ROOT / "debug_vision" / "20260510-032648_emit_a82f3c.jpg"


_OFFLINE_RESPONSE = json.dumps(
    {
        "tier": 3,
        "behavior_pattern": "taking_item",
        "confidence": 0.74,
        "scene": "front porch",
        "suspect_description": "tall person in dark jacket reaching for a package",
        "one_line_summary": "person bent over the porch and lifted an item before walking off",
        "time_elapsed": "ignored",
    }
)


@dataclass
class _StubText:
    text: str
    type: str = "text"


@dataclass
class _StubResp:
    content: list[_StubText]


class _StubMessages:
    def create(self, **_kwargs: object) -> _StubResp:
        return _StubResp(content=[_StubText(text=_OFFLINE_RESPONSE)])


class _StubClient:
    def __init__(self) -> None:
        self.messages = _StubMessages()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame", nargs="?", default=str(DEFAULT_FRAME))
    parser.add_argument(
        "--offline",
        action="store_true",
        help="swap the Anthropic client for a fixed-response stub",
    )
    args = parser.parse_args()

    frame_path = Path(args.frame)
    if not frame_path.exists():
        print(f"frame not found: {frame_path}")
        return 2

    frame_bgr = cv2.imread(str(frame_path))
    if frame_bgr is None:
        print(f"cv2 failed to decode {frame_path}")
        return 2

    clf = CloudHeavyClassifier(
        model=CONFIG.cloud_classifier_model,
        max_tokens=CONFIG.cloud_classifier_max_tokens,
        max_edge=CONFIG.cloud_classifier_max_edge,
        jpeg_quality=CONFIG.cloud_classifier_jpeg_quality,
        timeout_seconds=CONFIG.cloud_classifier_timeout_seconds,
        client=_StubClient() if args.offline else None,
    )

    mode = "offline-stub" if args.offline else "live-anthropic"
    print(f"frame={frame_path.name} model={CONFIG.cloud_classifier_model} mode={mode}")
    started = time.time()
    raw = clf.classify([frame_bgr], VISION_LANGUAGE_PROMPT)
    elapsed = time.time() - started

    print(f"--- raw response ({elapsed:.2f}s) ---")
    print(raw)
    print("--- evaluate_classifier_output ---")
    result = evaluate_classifier_output(raw, time_elapsed_seconds=elapsed)
    print(f"ok={result.ok} status={result.status} reason={result.reason}")
    if result.payload is not None:
        print(json.dumps(result.payload, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
