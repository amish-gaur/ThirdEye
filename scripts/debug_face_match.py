"""Diagnose face-filter matching against the enrolled DB.

Captures a single webcam frame (or reads a photo path), runs the same face
detector + embedder used by the live pipeline, and prints the cosine
similarity of every detected face against every enrolled embedding. Use this
to answer: "is my enrollment any good, and would the live pipeline match me?"

Usage examples
--------------

    # Live: smile at the webcam, captures one frame, prints similarity table
    python -m scripts.debug_face_match

    # Same but capture from a different camera index / RTSP url
    python -m scripts.debug_face_match --source 1

    # Run against a saved photo instead of the webcam
    python -m scripts.debug_face_match --image ~/Desktop/me.jpg

The output is a per-face similarity table:

    face #1  bbox=(178, 84) -> (322, 244)  size=144 px  det_score=0.93
      amish    : 0.62  best of 5 enrolled   (>= 0.45 threshold ✓ MATCH)
      brother  : 0.18  best of 3 enrolled
      ...
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from vision_pipeline.config import CONFIG
from vision_pipeline.face_filter import (
    FaceFilter,
    InsightFaceEmbedder,
    _box_short_edge,
)

log = logging.getLogger("scripts.debug_face_match")


def _read_image(path: Path) -> np.ndarray | None:
    try:
        with Image.open(path) as pil_img:
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            rgb = np.asarray(pil_img)
    except Exception as exc:
        log.error("Could not read %s: %s", path, exc)
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _capture_one_frame(source: str) -> np.ndarray | None:
    cap_source: int | str = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        log.error("Could not open camera source %r", source)
        return None
    # Burn a few frames so auto-exposure / white-balance settles.
    for _ in range(10):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        log.error("Camera grab failed for %r", source)
        return None
    return frame


def _format_table(filt: FaceFilter, frame: np.ndarray) -> str:
    faces = filt._embedder.detect_and_embed(frame)
    threshold = filt.similarity_threshold

    if not faces:
        return "No faces detected in the frame."

    lines: list[str] = [
        f"Detected {len(faces)} face(s). Threshold for MATCH = {threshold:.2f}.",
        "",
    ]

    for i, face in enumerate(faces, start=1):
        x1, y1, x2, y2 = (int(v) for v in face.bbox)
        edge = int(_box_short_edge(face.bbox))
        too_small = edge < filt.min_face_pixels
        flag = " (face_too_small)" if too_small else ""
        lines.append(
            f"face #{i}  bbox=({x1}, {y1}) -> ({x2}, {y2})  "
            f"short_edge={edge}px  det_score={face.det_score:.2f}{flag}"
        )

        scores = filt.all_match_scores(face.embedding)
        if not scores:
            lines.append("    (no enrolled people in DB)")
        else:
            best_name = max(scores, key=lambda n: scores[n])
            for name, sim in sorted(scores.items(), key=lambda kv: -kv[1]):
                marker = ""
                if name == best_name:
                    if sim >= threshold and not too_small:
                        marker = "  <-- MATCH"
                    elif sim >= threshold:
                        marker = "  (would match but face too small)"
                    else:
                        marker = f"  (closest, but below {threshold:.2f})"
                lines.append(f"    {name:<16} {sim:.3f}{marker}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print face-filter similarity scores for the current webcam frame "
        "(or a photo) against every enrolled person."
    )
    parser.add_argument(
        "--source", default=CONFIG.camera_source,
        help="Camera source for live capture (default: env CAMERA_SOURCE).",
    )
    parser.add_argument(
        "--image", default=None,
        help="Use this photo instead of the webcam. Respects EXIF rotation.",
    )
    parser.add_argument(
        "--db", default=CONFIG.face_db_path,
        help="Path to embeddings JSON (default: %(default)s).",
    )
    parser.add_argument(
        "--threshold", type=float, default=CONFIG.face_similarity_threshold,
        help="Match threshold to display (default: %(default)s).",
    )
    parser.add_argument(
        "--min-pixels", type=int, default=CONFIG.face_min_pixels,
        help="Minimum face short-edge in pixels (default: %(default)s).",
    )
    parser.add_argument(
        "--save", default=None,
        help="If set, save the captured frame here for inspection.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    if args.image:
        frame = _read_image(Path(args.image))
        if frame is None:
            return 2
    else:
        frame = _capture_one_frame(args.source)
        if frame is None:
            return 2

    if args.save:
        cv2.imwrite(args.save, frame)
        log.info("Saved captured frame to %s", args.save)

    filt = FaceFilter(
        db_path=args.db,
        similarity_threshold=args.threshold,
        min_face_pixels=args.min_pixels,
        embedder=InsightFaceEmbedder(),
    )

    if not filt.enrolled_names:
        print(f"Face DB at {args.db} is empty. Run scripts.enroll_face first.")
        return 1

    print(f"DB: {args.db}")
    print(f"Enrolled: {', '.join(filt.enrolled_names)}")
    print(f"Frame: {frame.shape[1]}x{frame.shape[0]}")
    print()
    print(_format_table(filt, frame))
    return 0


if __name__ == "__main__":
    sys.exit(main())
