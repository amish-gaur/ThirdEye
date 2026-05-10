"""Enroll a family member into the face exclusion database.

Usage examples
--------------

Enroll from a folder of photos:

    python -m scripts.enroll_face --name amish --photos family_faces/amish/*.jpg

Capture live frames from the webcam (press SPACE to capture, ESC to finish):

    python -m scripts.enroll_face --name amish --webcam --captures 5

The resulting embeddings are appended to ``FACE_DB_PATH`` (default
``./family_faces/embeddings.json``). Run repeatedly to add more photos /
people; existing entries are merged, never overwritten.
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
import time
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from PIL import Image, ImageOps

from vision_pipeline.config import CONFIG
from vision_pipeline.face_filter import (
    FaceEmbedder,
    FaceEmbedding,
    InsightFaceEmbedder,
    save_database,
)


# iPhone photos are often 4000+ px on the long edge; the buffalo_s detector
# is set up for 320 px tiles, so a face that's 100 px in a 4000 px image
# becomes ~8 px after downscale and is missed. Pre-resize to a friendlier size.
_MAX_LONG_EDGE_PX = 1600


def _read_image_respecting_exif(path: Path) -> np.ndarray | None:
    """Read an image as BGR uint8, applying EXIF rotation and downscaling
    huge iPhone photos so the detector can find small faces.

    cv2.imread ignores EXIF, so portrait iPhone photos load sideways and the
    face detector silently misses them. PIL respects EXIF.
    """
    try:
        with Image.open(path) as pil_img:
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            w, h = pil_img.size
            long_edge = max(w, h)
            if long_edge > _MAX_LONG_EDGE_PX:
                scale = _MAX_LONG_EDGE_PX / float(long_edge)
                pil_img = pil_img.resize(
                    (int(w * scale), int(h * scale)), Image.Resampling.LANCZOS
                )
            rgb = np.asarray(pil_img)
    except Exception as exc:  # PIL.UnidentifiedImageError, OSError, etc.
        log.warning("Could not read %s: %s", path, exc)
        return None
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

log = logging.getLogger("scripts.enroll_face")


def _expand_photo_args(patterns: Iterable[str]) -> list[Path]:
    """Expand glob patterns + bare paths into a sorted list of files."""
    out: list[Path] = []
    for raw in patterns:
        matches = glob.glob(raw)
        if not matches and Path(raw).exists():
            matches = [raw]
        for m in matches:
            p = Path(m)
            if p.is_file():
                out.append(p)
    # Stable order so re-running enrollment is deterministic.
    return sorted(set(out))


def _embed_image(
    path: Path, embedder: FaceEmbedder, *, debug_dir: Path | None = None
) -> FaceEmbedding | None:
    img = _read_image_respecting_exif(path)
    if img is None:
        return None
    faces = embedder.detect_and_embed(img)
    if debug_dir is not None:
        _save_debug_annotation(img, faces, debug_dir / f"debug_{path.stem}.jpg")
    if not faces:
        log.warning(
            "No face detected in %s (size=%dx%d). "
            "Try a closer photo with one face clearly visible.",
            path,
            img.shape[1],
            img.shape[0],
        )
        return None
    if len(faces) > 1:
        log.warning(
            "%d faces detected in %s; using the largest. Crop the photo to one "
            "person for best results.",
            len(faces),
            path,
        )
    return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


def _save_debug_annotation(
    bgr: np.ndarray, faces: list[FaceEmbedding], out_path: Path
) -> None:
    """Save a copy of the input photo with detected face boxes drawn on top."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    annotated = bgr.copy()
    for face in faces:
        x1, y1, x2, y2 = (int(v) for v in face.bbox)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3)
        cv2.putText(
            annotated,
            f"face {face.det_score:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
    if not faces:
        cv2.putText(
            annotated,
            "NO FACE DETECTED",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(out_path), annotated)


def _capture_from_webcam(
    *, source: str, count: int, embedder: FaceEmbedder
) -> list[np.ndarray]:
    """Open a webcam preview and let the user capture N face frames.

    Returns the list of L2-normalized embeddings (length <= count).
    """
    cap_source: int | str = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera source {source!r}")

    captured: list[np.ndarray] = []
    print("Webcam open. SPACE to capture a frame, ESC to finish.")

    try:
        while len(captured) < count:
            ok, frame = cap.read()
            if not ok:
                continue

            preview = frame.copy()
            faces = embedder.detect_and_embed(frame)
            for face in faces:
                x1, y1, x2, y2 = (int(v) for v in face.bbox)
                cv2.rectangle(preview, (x1, y1), (x2, y2), (0, 255, 0), 2)
            status = f"captured {len(captured)}/{count}  faces in view: {len(faces)}"
            cv2.putText(
                preview,
                status,
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 0),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                preview,
                status,
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (240, 240, 240),
                1,
                cv2.LINE_AA,
            )
            cv2.imshow("Enroll face", preview)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break
            if key == 32:  # SPACE
                if not faces:
                    print("No face visible — move closer / improve lighting.")
                    continue
                face = max(
                    faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                )
                captured.append(face.embedding)
                print(f"  ✓ captured {len(captured)}/{count}")
                # Brief flash.
                flash = np.full_like(preview, 255)
                cv2.imshow("Enroll face", flash)
                cv2.waitKey(80)
                time.sleep(0.2)
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return captured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enroll a family member into the face exclusion database used by "
            "the ThirdEye vision pipeline."
        )
    )
    parser.add_argument("--name", required=True, help="Person's name (e.g. 'amish').")
    parser.add_argument(
        "--photos",
        nargs="*",
        default=[],
        help="Photo paths or glob patterns. Each photo should show one face clearly.",
    )
    parser.add_argument(
        "--webcam",
        action="store_true",
        help="Capture face frames live from the webcam.",
    )
    parser.add_argument(
        "--webcam-source",
        default=CONFIG.camera_source,
        help="Camera source for --webcam mode (defaults to CAMERA_SOURCE env).",
    )
    parser.add_argument(
        "--captures",
        type=int,
        default=5,
        help="Number of webcam frames to capture (default: 5).",
    )
    parser.add_argument(
        "--db",
        default=CONFIG.face_db_path,
        help="Path to embeddings JSON (default: %(default)s).",
    )
    parser.add_argument(
        "--debug-dir",
        default=None,
        help=(
            "If set, write annotated copies of every input photo here so you "
            "can see what the detector saw (or didn't). Useful when faces are "
            "missed."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    if not args.photos and not args.webcam:
        parser.error("Provide --photos and/or --webcam.")

    embedder = InsightFaceEmbedder()
    embeddings: list[np.ndarray] = []

    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    if args.photos:
        photo_paths = _expand_photo_args(args.photos)
        if not photo_paths:
            log.error("No photos matched %s", args.photos)
            return 2
        log.info("Embedding %d photo(s) for %s", len(photo_paths), args.name)
        for path in photo_paths:
            face = _embed_image(path, embedder, debug_dir=debug_dir)
            if face is not None:
                embeddings.append(face.embedding)
        if debug_dir is not None:
            log.info("Annotated debug images written to %s", debug_dir)

    if args.webcam:
        captured = _capture_from_webcam(
            source=args.webcam_source, count=args.captures, embedder=embedder
        )
        embeddings.extend(captured)

    if not embeddings:
        log.error("No usable embeddings produced; nothing written.")
        return 1

    save_database(args.db, {args.name: embeddings})
    log.info(
        "Wrote %d embedding(s) for %s to %s",
        len(embeddings),
        args.name,
        args.db,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
