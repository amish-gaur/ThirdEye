#!/usr/bin/env python3
"""Extract a person crop from a video file at a given timestamp + bbox.

Used to populate tests/fixtures/reid/ once demo footage exists.

    python scripts/build_reid_fixtures.py \\
        --video data/demo/cam_1.mp4 \\
        --label person_A_cam1 \\
        --time 12.5 \\
        --bbox 220,80,360,420
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "reid"


def parse_bbox(s: str) -> tuple[int, int, int, int]:
    parts = [int(p.strip()) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be x1,y1,x2,y2")
    return tuple(parts)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--video", required=True, type=Path)
    p.add_argument("--label", required=True,
                   help="Output filename stem, e.g. person_A_cam1")
    p.add_argument("--time", required=True, type=float,
                   help="Seek time in seconds")
    p.add_argument("--bbox", required=True, type=parse_bbox,
                   help="Bbox as x1,y1,x2,y2 in pixels")
    p.add_argument("--out-dir", type=Path, default=FIXTURE_DIR)
    args = p.parse_args(argv)

    if not args.video.exists():
        print(f"video not found: {args.video}", file=sys.stderr)
        return 1

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"could not open {args.video}", file=sys.stderr)
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_idx = int(round(args.time * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        print(f"could not read frame at t={args.time}s (idx={frame_idx})",
              file=sys.stderr)
        return 1

    x1, y1, x2, y2 = args.bbox
    h, w = frame.shape[:2]
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(x1 + 1, min(x2, w))
    y2 = max(y1 + 1, min(y2, h))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        print(f"empty crop after clamping; bbox out of frame", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{args.label}.jpg"
    cv2.imwrite(str(out), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"wrote {out}  ({crop.shape[1]}x{crop.shape[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
