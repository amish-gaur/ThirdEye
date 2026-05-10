#!/usr/bin/env python3
"""Generate fake 3-camera footage from Ultralytics' bundled person images.

Crops real people out of `bus.jpg` and `zidane.jpg`, composites them
onto plain backgrounds at moving positions, and writes one mp4 per
"camera". Lets us smoke-test the full cross-camera pipeline (YOLO
tracking + ReID + tag parsing + MCP search) without recording real
footage.

Usage:
    .venv/bin/python -m scripts.make_fake_multicam --out data/demo

After this finishes:
    .venv/bin/python -m scripts.replay_multicam \\
        --video cam_1=data/demo/cam_1.mp4 \\
        --video cam_2=data/demo/cam_2.mp4 \\
        --video cam_3=data/demo/cam_3.mp4 \\
        --db data/tracks.db --media-root data/media \\
        --no-qwen
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("scripts.make_fake_multicam")


@dataclass(frozen=True)
class PersonCrop:
    label: str
    rgba: np.ndarray  # H x W x 4 (BGR + alpha)


def _load_ultralytics_assets() -> tuple[Path, Path]:
    """Return paths to the bundled bus.jpg + zidane.jpg."""
    import ultralytics
    root = Path(ultralytics.__file__).parent / "assets"
    bus = root / "bus.jpg"
    zid = root / "zidane.jpg"
    if not bus.exists() or not zid.exists():
        raise FileNotFoundError(
            f"could not find ultralytics assets at {root}; "
            "is ultralytics installed?"
        )
    return bus, zid


def _detect_people(image_path: Path, conf: float = 0.5) -> list[tuple[int, int, int, int]]:
    """Run YOLO11n and return person bboxes (x1, y1, x2, y2)."""
    from ultralytics import YOLO

    model = YOLO("yolo11n.pt")
    results = model(str(image_path), classes=[0], conf=conf, verbose=False)
    out: list[tuple[int, int, int, int]] = []
    for r in results:
        if r.boxes is None:
            continue
        for box in r.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = (int(round(v)) for v in box)
            out.append((x1, y1, x2, y2))
    return out


def _make_alpha_crop(bgr_image: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    """Crop bbox + add alpha channel (full opacity, edge feather)."""
    x1, y1, x2, y2 = bbox
    crop_bgr = bgr_image[y1:y2, x1:x2]
    h, w = crop_bgr.shape[:2]
    alpha = np.full((h, w), 255, dtype=np.uint8)
    feather = 8
    # Feather edges so composite doesn't show hard rectangle outlines
    if h > 2 * feather and w > 2 * feather:
        for i in range(feather):
            v = int(round(255 * (i + 1) / feather))
            alpha[i, :] = np.minimum(alpha[i, :], v)
            alpha[-(i + 1), :] = np.minimum(alpha[-(i + 1), :], v)
            alpha[:, i] = np.minimum(alpha[:, i], v)
            alpha[:, -(i + 1)] = np.minimum(alpha[:, -(i + 1)], v)
    return np.dstack([crop_bgr, alpha])


def _composite(
    background: np.ndarray, sprite_rgba: np.ndarray, x: int, y: int,
) -> None:
    """In-place alpha composite sprite onto background at (x, y)."""
    sh, sw = sprite_rgba.shape[:2]
    bh, bw = background.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(bw, x + sw)
    y2 = min(bh, y + sh)
    if x2 <= x1 or y2 <= y1:
        return
    sx1 = x1 - x
    sy1 = y1 - y
    sx2 = sx1 + (x2 - x1)
    sy2 = sy1 + (y2 - y1)
    bg_region = background[y1:y2, x1:x2]
    sprite_bgr = sprite_rgba[sy1:sy2, sx1:sx2, :3]
    sprite_a = sprite_rgba[sy1:sy2, sx1:sx2, 3:4].astype(np.float32) / 255.0
    blended = sprite_bgr.astype(np.float32) * sprite_a + bg_region.astype(np.float32) * (1.0 - sprite_a)
    background[y1:y2, x1:x2] = blended.astype(np.uint8)


def _make_background(width: int, height: int, hue: int, frame_idx: int) -> np.ndarray:
    """Distinct, time-varying background per camera so each cam looks different."""
    bg = np.zeros((height, width, 3), dtype=np.uint8)
    base_v = 60 + (frame_idx % 5) * 4  # subtle flicker so video isn't static
    bg[:] = (
        max(0, base_v - 20),
        max(0, base_v - 10),
        base_v,
    )
    # Stripe to give YOLO some texture
    cv2.line(bg, (0, height // 2), (width, height // 2),
             (hue, 100, 80), thickness=2)
    cv2.putText(bg, f"cam frame {frame_idx}", (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
    return bg


@dataclass
class _Spawn:
    person: PersonCrop
    start_frame: int
    end_frame: int
    start_xy: tuple[int, int]
    end_xy: tuple[int, int]
    scale: float = 1.0


def _render_camera(
    out_path: Path,
    n_frames: int,
    fps: int,
    width: int,
    height: int,
    hue: int,
    spawns: list[_Spawn],
) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, float(fps), (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"could not open writer for {out_path}")
    try:
        for f in range(n_frames):
            bg = _make_background(width, height, hue, f)
            for s in spawns:
                if not (s.start_frame <= f <= s.end_frame):
                    continue
                t = (f - s.start_frame) / max(1, s.end_frame - s.start_frame)
                x = int(round(s.start_xy[0] + t * (s.end_xy[0] - s.start_xy[0])))
                y = int(round(s.start_xy[1] + t * (s.end_xy[1] - s.start_xy[1])))
                sprite = s.person.rgba
                if s.scale != 1.0:
                    sh, sw = sprite.shape[:2]
                    sprite = cv2.resize(
                        sprite,
                        (max(1, int(sw * s.scale)), max(1, int(sh * s.scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                _composite(bg, sprite, x, y)
            writer.write(bg)
    finally:
        writer.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/demo"))
    parser.add_argument("--frames", type=int, default=80,
                        help="frames per camera (default 80 ≈ 8 seconds at 10fps)")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args.out.mkdir(parents=True, exist_ok=True)

    bus_path, zidane_path = _load_ultralytics_assets()
    log.info("detecting people in bundled assets...")
    bus_img = cv2.imread(str(bus_path))
    zid_img = cv2.imread(str(zidane_path))
    bus_boxes = _detect_people(bus_path, conf=0.5)
    zid_boxes = _detect_people(zidane_path, conf=0.5)
    log.info("bus.jpg: %d people, zidane.jpg: %d people",
             len(bus_boxes), len(zid_boxes))
    if len(bus_boxes) < 2 or len(zid_boxes) < 1:
        print("ERROR: not enough people detected in bundled assets",
              file=sys.stderr)
        return 1

    # Sort left to right for predictable labeling.
    bus_boxes.sort(key=lambda b: b[0])
    zid_boxes.sort(key=lambda b: b[0])

    person_a = PersonCrop("A_bus_left", _make_alpha_crop(bus_img, bus_boxes[0]))
    person_b = PersonCrop("B_bus_right", _make_alpha_crop(bus_img, bus_boxes[-1]))
    person_c = PersonCrop("C_zidane", _make_alpha_crop(zid_img, zid_boxes[0]))
    log.info("person_A %s; person_B %s; person_C %s",
             person_a.rgba.shape, person_b.rgba.shape, person_c.rgba.shape)

    # cam_1: person_A walks left→right (alone)
    # cam_2: person_A walks right→left (same person, different cam) +
    #        person_B walks left→right after a delay (different person)
    # cam_3: person_B walks left→right + person_C appears later
    n = args.frames
    cam_specs = {
        "cam_1": (50, [
            _Spawn(person_a, 0, n - 1,
                   start_xy=(50, 200), end_xy=(args.width - 250, 200),
                   scale=1.0),
        ]),
        "cam_2": (120, [
            _Spawn(person_a, 5, n - 5,
                   start_xy=(args.width - 250, 220),
                   end_xy=(50, 220),
                   scale=1.0),
            _Spawn(person_b, n // 3, n - 1,
                   start_xy=(40, 240), end_xy=(args.width - 200, 240),
                   scale=1.0),
        ]),
        "cam_3": (30, [
            _Spawn(person_b, 0, int(n * 0.7),
                   start_xy=(50, 230), end_xy=(args.width - 200, 230),
                   scale=1.0),
            _Spawn(person_c, n // 2, n - 1,
                   start_xy=(args.width - 250, 200),
                   end_xy=(80, 200),
                   scale=1.0),
        ]),
    }

    for cam_id, (hue, spawns) in cam_specs.items():
        out = args.out / f"{cam_id}.mp4"
        log.info("rendering %s -> %s", cam_id, out)
        _render_camera(
            out_path=out,
            n_frames=n, fps=args.fps,
            width=args.width, height=args.height,
            hue=hue, spawns=spawns,
        )
        log.info("  wrote %s (%d bytes)", out, out.stat().st_size)

    print()
    print("=== fake multicam ready ===")
    for cam_id in cam_specs:
        print(f"  {args.out / f'{cam_id}.mp4'}")
    print()
    print("Crops used:")
    print(f"  person_A (bus left)    → cam_1, cam_2  (SAME PERSON)")
    print(f"  person_B (bus right)   → cam_2, cam_3  (SAME PERSON)")
    print(f"  person_C (zidane.jpg)  → cam_3 only")
    print()
    print("Next:")
    print(f"  .venv/bin/python -m scripts.replay_multicam \\")
    for cam_id in cam_specs:
        print(f"      --video {cam_id}={args.out / f'{cam_id}.mp4'} \\")
    print(f"      --db data/tracks.db --media-root data/media --no-qwen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
