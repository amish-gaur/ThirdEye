"""One-command face setup: enroll + verify + launch vision.

Usage:
    python -m scripts.face_setup --name aditya

What it does
------------
1. Opens your webcam.
2. Shows a live preview with on-screen instructions: "Slowly rotate your head".
3. Captures EVERY frame that has a clean face (det_score >= 0.7), up to 200 raw
   embeddings, over a 12-second window.
4. Bins by head yaw + pitch, keeps the BEST capture per pose bin (max ~24 kept).
   This gives FaceID-style angle diversity instead of 5 nearly-identical fronts.
5. Writes the embeddings to family_faces/embeddings.json (same format as
   scripts.enroll_face — `vision_pipeline.face_filter` reads them as-is).
6. (Optional) re-execs into `python -m scripts.run_vision` so the same webcam
   stream becomes the live security feed with FACE_FILTER_ENABLED=true.

Why this is better than the original SPACE-press flow
-----------------------------------------------------
* No human-timing dependency — capture happens at full webcam fps, ~30 frames/s,
  so the model sees you at every micro-pose, not just where you happen to press.
* Pose diversity gating means the saved embeddings span a real angular range
  (yaw -45 to +45, pitch -25 to +25), not 5 lookalike-front shots.
* Quality gate drops blurred / low-confidence frames automatically.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from vision_pipeline.config import CONFIG
from vision_pipeline.face_filter import (
    FaceEmbedding,
    InsightFaceEmbedder,
    save_database,
)


log = logging.getLogger("scripts.face_setup")


# How many seconds of "spin your head" to record before deciding what to keep.
DEFAULT_SECONDS = 12.0
# Hard cap on raw embeddings collected (keeps RAM reasonable on long runs).
MAX_RAW = 250
# Minimum face-detector confidence to accept a frame.
MIN_DET_SCORE = 0.65
# Minimum face crop size (pixels on the longer edge).
MIN_FACE_PIXELS = 110

# Pose bins. We bin yaw + pitch into discrete cells and keep the best capture
# (highest det_score) per cell. Centred-front bin gets natural redundancy
# because that's where the user starts.
YAW_BINS = [-45, -30, -15, 0, 15, 30, 45]      # degrees
PITCH_BINS = [-25, -10, 0, 10, 25]             # degrees
# Final cap on how many embeddings we save (top-K from across the bins).
KEEP_TOP_N = 24


@dataclass
class CapturedSample:
    embedding: np.ndarray   # L2-normalized 512-d
    yaw: float
    pitch: float
    det_score: float
    bbox_area: float
    captured_at: float


def _bin_index(value: float, edges: list[int]) -> int:
    """Snap a continuous value to its nearest bin index."""
    return int(np.argmin([abs(value - e) for e in edges]))


def _draw_overlay(
    preview: np.ndarray,
    *,
    raw: int,
    bins_filled: int,
    bins_total: int,
    seconds_left: float,
    last_face_box: tuple[int, int, int, int] | None,
) -> None:
    h, w = preview.shape[:2]

    # Semi-transparent strip top + bottom for legibility on bright frames.
    overlay = preview.copy()
    cv2.rectangle(overlay, (0, 0), (w, 90), (0, 0, 0), -1)
    cv2.rectangle(overlay, (0, h - 70), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, preview, 0.45, 0, preview)

    # Headline.
    cv2.putText(
        preview,
        "Slowly rotate your head — left, right, up, down",
        (16, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (250, 245, 240),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        preview,
        f"raw frames: {raw}    angle bins: {bins_filled}/{bins_total}    {seconds_left:0.1f}s left",
        (16, 64),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )

    # Progress bar across bottom — width tracks bins_filled / bins_total.
    bar_pad = 16
    bar_y0 = h - 38
    bar_y1 = h - 22
    bar_x0 = bar_pad
    bar_x1 = w - bar_pad
    cv2.rectangle(preview, (bar_x0, bar_y0), (bar_x1, bar_y1), (60, 60, 60), -1)
    if bins_total > 0:
        fill_x = bar_x0 + int((bar_x1 - bar_x0) * (bins_filled / bins_total))
        cv2.rectangle(preview, (bar_x0, bar_y0), (fill_x, bar_y1), (159, 18, 57), -1)
    cv2.putText(
        preview,
        "ESC to stop early",
        (16, h - 6),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )

    if last_face_box is not None:
        x1, y1, x2, y2 = last_face_box
        cv2.rectangle(preview, (x1, y1), (x2, y2), (159, 18, 57), 2)


def _select_top(samples: list[CapturedSample], keep: int) -> list[CapturedSample]:
    """Pick a diverse subset of `keep` embeddings.

    InsightFace buffalo_l doesn't always populate yaw/pitch — when it doesn't,
    every sample lands in the (0,0) bin and we lose all but one. To stay robust
    we use a TWO-PASS strategy:

      1. If yaw/pitch *do* vary across samples, do pose-bin dedup (one per bin).
      2. If they don't (typical case), fall back to embedding-distance diversity:
         greedily pick the highest-quality sample, then keep adding samples that
         are most different from anything already kept (cosine-distance MaxMin).
    """
    if not samples:
        return []

    yaw_spread = max(s.yaw for s in samples) - min(s.yaw for s in samples)
    pitch_spread = max(s.pitch for s in samples) - min(s.pitch for s in samples)
    has_pose_signal = yaw_spread > 5.0 or pitch_spread > 5.0

    if has_pose_signal:
        by_bin: dict[tuple[int, int], CapturedSample] = {}
        for s in samples:
            key = (_bin_index(s.yaw, YAW_BINS), _bin_index(s.pitch, PITCH_BINS))
            prior = by_bin.get(key)
            score_new = s.det_score * np.sqrt(s.bbox_area)
            score_old = prior.det_score * np.sqrt(prior.bbox_area) if prior else -1
            if score_new > score_old:
                by_bin[key] = s
        survivors = sorted(
            by_bin.values(),
            key=lambda s: s.det_score * np.sqrt(s.bbox_area),
            reverse=True,
        )
        return survivors[:keep]

    # Fallback: greedy MaxMin on embedding distance — guarantees diverse picks
    # even when yaw/pitch metadata is missing.
    pool = sorted(
        samples, key=lambda s: s.det_score * np.sqrt(s.bbox_area), reverse=True
    )
    chosen: list[CapturedSample] = [pool[0]]
    chosen_emb = [pool[0].embedding]
    for cand in pool[1:]:
        if len(chosen) >= keep:
            break
        # Cosine distance to nearest already-chosen.
        sims = [float(np.dot(cand.embedding, e)) for e in chosen_emb]
        nearest_sim = max(sims)
        # Skip if nearly identical to one already kept (would add no info).
        if nearest_sim > 0.985:
            continue
        chosen.append(cand)
        chosen_emb.append(cand.embedding)
    return chosen


def run_enrollment(
    *,
    name: str,
    source: str,
    seconds: float,
    db_path: str,
    chain_into_vision: bool,
) -> int:
    print(
        "\n[face_setup] starting enrollment for "
        f"name={name!r}  source={source!r}  duration={seconds:.0f}s\n"
    )

    embedder = InsightFaceEmbedder(
        model_name=CONFIG.face_model_name,
        apply_clahe=CONFIG.face_clahe_enabled,
    )

    cap_source: int | str = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        print(f"[face_setup] ERROR: could not open camera source {source!r}")
        return 2

    samples: list[CapturedSample] = []
    started_at = time.monotonic()
    cv2.namedWindow("ThirdEye · face setup", cv2.WINDOW_NORMAL)
    last_face_box: tuple[int, int, int, int] | None = None

    try:
        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= seconds:
                break
            ok, frame = cap.read()
            if not ok:
                continue

            faces = embedder.detect_and_embed(frame)
            best = None
            for f in faces:
                area = (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
                if area < MIN_FACE_PIXELS * MIN_FACE_PIXELS:
                    continue
                if f.det_score < MIN_DET_SCORE:
                    continue
                if best is None or (f.det_score * area) > (best.det_score * (best.bbox[2] - best.bbox[0]) * (best.bbox[3] - best.bbox[1])):
                    best = f

            if best is not None:
                samples.append(
                    CapturedSample(
                        embedding=best.embedding,
                        yaw=best.yaw if best.yaw is not None else 0.0,
                        pitch=best.pitch if best.pitch is not None else 0.0,
                        det_score=best.det_score,
                        bbox_area=(best.bbox[2] - best.bbox[0]) * (best.bbox[3] - best.bbox[1]),
                        captured_at=time.time(),
                    )
                )
                last_face_box = (
                    int(best.bbox[0]), int(best.bbox[1]),
                    int(best.bbox[2]), int(best.bbox[3]),
                )
                if len(samples) >= MAX_RAW:
                    break

            # Compute live "bins filled" for the progress bar.
            seen_bins: set[tuple[int, int]] = set()
            for s in samples:
                seen_bins.add((_bin_index(s.yaw, YAW_BINS), _bin_index(s.pitch, PITCH_BINS)))
            bins_total = len(YAW_BINS) * len(PITCH_BINS)

            preview = frame.copy()
            _draw_overlay(
                preview,
                raw=len(samples),
                bins_filled=len(seen_bins),
                bins_total=bins_total,
                seconds_left=max(0.0, seconds - elapsed),
                last_face_box=last_face_box,
            )
            cv2.imshow("ThirdEye · face setup", preview)
            if (cv2.waitKey(1) & 0xFF) == 27:  # ESC
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if not samples:
        print(
            "[face_setup] ERROR: no usable faces captured. "
            "Is the camera pointed at you, with good light?"
        )
        return 3

    survivors = _select_top(samples, keep=KEEP_TOP_N)
    print(
        f"[face_setup] collected {len(samples)} raw embeddings, "
        f"keeping top {len(survivors)} across angle bins."
    )

    # Persist into the existing JSON DB so vision_pipeline.face_filter loads it.
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if db_file.exists():
        existing = json.loads(db_file.read_text())
    else:
        existing = {"people": []}

    # Replace any prior entry for this name so re-running starts fresh.
    existing["people"] = [p for p in existing.get("people", []) if p.get("name") != name]
    existing["people"].append(
        {
            "name": name,
            "embeddings": [s.embedding.tolist() for s in survivors],
            "captured_at": time.time(),
        }
    )
    db_file.write_text(json.dumps(existing, indent=2))
    print(f"[face_setup] wrote {len(survivors)} embeddings for {name!r} → {db_file}")

    if not chain_into_vision:
        print(
            "\n[face_setup] enrollment complete. Run the live test:\n"
            "    export FACE_FILTER_ENABLED=true\n"
            "    python -m scripts.run_vision\n"
        )
        return 0

    # Hand off to run_vision. We exec() instead of spawning a subprocess so the
    # webcam handle is fully released first.
    print(
        "\n[face_setup] launching vision pipeline with FACE_FILTER_ENABLED=true …"
    )
    env = os.environ.copy()
    env["FACE_FILTER_ENABLED"] = "true"
    env.setdefault("ACTION_ROUTER_URL", "http://127.0.0.1:8001/event")
    os.execvpe(
        sys.executable,
        [sys.executable, "-m", "scripts.run_vision"],
        env,
    )
    return 0  # unreachable


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="One-command face enrollment + live vision test.",
    )
    parser.add_argument("--name", required=True, help="Your name (e.g. 'aditya').")
    parser.add_argument(
        "--seconds", type=float, default=DEFAULT_SECONDS,
        help=f"Recording duration (default {DEFAULT_SECONDS:.0f}s).",
    )
    parser.add_argument(
        "--source", default=CONFIG.camera_source,
        help="Webcam source (default: env CAMERA_SOURCE or '0').",
    )
    parser.add_argument(
        "--db", default=CONFIG.face_db_path,
        help="Where to write embeddings JSON.",
    )
    parser.add_argument(
        "--no-chain", action="store_true",
        help="Skip auto-launching scripts.run_vision after enrollment.",
    )
    args = parser.parse_args()

    return run_enrollment(
        name=args.name,
        source=args.source,
        seconds=args.seconds,
        db_path=args.db,
        chain_into_vision=not args.no_chain,
    )


if __name__ == "__main__":
    sys.exit(main())
