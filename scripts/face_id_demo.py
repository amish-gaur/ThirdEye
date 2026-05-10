"""Standalone face-recognition demo.

Isolated from the rest of the ThirdEye pipeline. Does not import or modify
``vision_pipeline.*`` or ``action_router.*``. Stores its own gallery in
``face_demo/gallery.json`` so the existing ``family_faces/`` enrollment is
left alone.

Stack (per the M3 research path):
    InsightFace ``buffalo_l`` (ArcFace / ResNet-50 / WebFace600K)
    CoreML execution provider on the Apple Neural Engine
    L2-normalised cosine similarity, top-K-mean match
    Diversity-aware enrollment via cosine-distance bucketing

Subcommands
-----------
    enroll  - open the camera, capture pose-diverse embeddings of one person
    detect  - open the camera, label every face live with name + score
    status  - print the gallery contents + active ORT providers and exit

The detector and the recognizer ship in the same ``buffalo_l`` package, so
no Apple Vision / cloud detour is needed for the isolated demo.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import onnxruntime as ort

log = logging.getLogger("face_id_demo")

REPO_ROOT = Path(__file__).resolve().parent.parent
GALLERY_PATH = REPO_ROOT / "face_demo" / "gallery.json"

MODEL_NAME = "buffalo_l"
PROVIDERS = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
DET_SIZE = (640, 640)

# Match knobs — buffalo_l on WebFace600K. Community defaults: 0.40-0.50.
# We default a touch stricter than the existing face_filter (0.45 vs 0.40)
# because with proper diverse enrollment + CoreML the cluster is tighter.
SIM_THRESHOLD = 0.45
TOPK_MEAN = 3

# Enrollment quality gates.
MIN_DET_SCORE = 0.55
MIN_FACE_PIXELS = 96
MAX_GALLERY_SIZE = 30

# A new sample is kept only if its cosine sim to every already-kept sample
# is below this — drops near-duplicates so the gallery actually spans poses.
DEDUP_SIM_MAX = 0.93


@dataclass
class GalleryEntry:
    name: str
    embedding: np.ndarray  # L2-normalised float32 [512]
    det_score: float
    captured_at: float


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def make_app():
    """Build a FaceAnalysis pinned to CoreML, with a fail-soft to CPU.

    Importing inside the function so ``status`` can run without dragging in
    onnxruntime quirks if the user just wants to inspect the gallery.
    """
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name=MODEL_NAME, providers=PROVIDERS)
    app.prepare(ctx_id=0, det_size=DET_SIZE)
    chosen = []
    for model_name, model in app.models.items():
        sess = getattr(model, "session", None)
        if sess is not None:
            chosen.append((model_name, list(sess.get_providers())))
    log.info("FaceAnalysis providers per model: %s", chosen)
    if not any("CoreMLExecutionProvider" in providers for _, providers in chosen):
        log.warning(
            "CoreMLExecutionProvider not active on any model. Falling back to CPU. "
            "Available providers: %s",
            ort.get_available_providers(),
        )
    return app


def open_camera(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise SystemExit(f"could not open camera index {index}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


# ---------------------------------------------------------------------------
# Gallery I/O
# ---------------------------------------------------------------------------


def load_gallery() -> list[GalleryEntry]:
    if not GALLERY_PATH.exists():
        return []
    raw = json.loads(GALLERY_PATH.read_text())
    out: list[GalleryEntry] = []
    for row in raw.get("entries", []):
        emb = np.asarray(row["embedding"], dtype=np.float32)
        out.append(
            GalleryEntry(
                name=row["name"],
                embedding=emb,
                det_score=float(row.get("det_score", 1.0)),
                captured_at=float(row.get("captured_at", 0.0)),
            )
        )
    return out


def save_gallery(entries: list[GalleryEntry]) -> None:
    GALLERY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "entries": [
            {
                "name": e.name,
                "embedding": e.embedding.astype(float).tolist(),
                "det_score": e.det_score,
                "captured_at": e.captured_at,
            }
            for e in entries
        ]
    }
    GALLERY_PATH.write_text(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def l2norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-9:
        return v
    return v / n


def best_match(probe: np.ndarray, gallery: list[GalleryEntry]) -> tuple[str, float]:
    """Return (name, mean-of-top-K cosine sim). Empty gallery -> ("", -1)."""
    if not gallery:
        return ("", -1.0)
    by_name: dict[str, list[float]] = {}
    for e in gallery:
        by_name.setdefault(e.name, []).append(float(np.dot(probe, e.embedding)))
    best_name, best_score = "", -1.0
    for name, sims in by_name.items():
        sims.sort(reverse=True)
        k = min(TOPK_MEAN, len(sims))
        mean = float(np.mean(sims[:k]))
        if mean > best_score:
            best_name, best_score = name, mean
    return best_name, best_score


def face_too_small(face) -> bool:
    x1, y1, x2, y2 = face.bbox.astype(int)
    return min(x2 - x1, y2 - y1) < MIN_FACE_PIXELS


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_status(_args) -> int:
    print(f"gallery: {GALLERY_PATH}")
    if not GALLERY_PATH.exists():
        print("  (empty — run `enroll` first)")
    else:
        entries = load_gallery()
        per_name: dict[str, int] = {}
        for e in entries:
            per_name[e.name] = per_name.get(e.name, 0) + 1
        for name, n in sorted(per_name.items()):
            print(f"  {name}: {n} embeddings")
    print(f"available ORT providers: {ort.get_available_providers()}")
    print(f"requested providers:    {PROVIDERS}")
    return 0


def cmd_enroll(args) -> int:
    app = make_app()
    cap = open_camera(args.camera)
    existing = load_gallery() if args.append else []
    if not args.append:
        # Wipe entries for this name only; preserve other people if any.
        existing = [e for e in load_gallery() if e.name != args.name]
    log.info("starting enrollment for %s for %ds", args.name, args.seconds)

    new_entries: list[GalleryEntry] = []
    deadline = time.monotonic() + args.seconds
    last_status_log = 0.0
    raw_frames = 0

    try:
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                continue
            raw_frames += 1
            faces = app.get(frame)

            kept_this_frame = False
            status = "looking..."
            primary = None
            if len(faces) == 0:
                status = "no face"
            else:
                # Closest face = largest bbox area = the subject. Don't refuse
                # enrollment over background people / posters / reflections.
                def _area(f):
                    x1, y1, x2, y2 = f.bbox
                    return max(0.0, x2 - x1) * max(0.0, y2 - y1)
                primary = max(faces, key=_area)
            if primary is not None:
                face = primary
                if face.det_score < MIN_DET_SCORE:
                    status = f"low quality ({face.det_score:.2f})"
                elif face_too_small(face):
                    status = "too far — come closer"
                else:
                    emb = l2norm(np.asarray(face.normed_embedding, dtype=np.float32))
                    if all(
                        float(np.dot(emb, e.embedding)) < DEDUP_SIM_MAX
                        for e in new_entries
                    ):
                        new_entries.append(
                            GalleryEntry(
                                name=args.name,
                                embedding=emb,
                                det_score=float(face.det_score),
                                captured_at=time.time(),
                            )
                        )
                        kept_this_frame = True
                        if len(new_entries) >= MAX_GALLERY_SIZE:
                            log.info(
                                "hit MAX_GALLERY_SIZE=%d — stopping early",
                                MAX_GALLERY_SIZE,
                            )
                            break
                    extra = (
                        f"  (+{len(faces) - 1} ignored)" if len(faces) > 1 else ""
                    )
                    status = (
                        f"captured ({len(new_entries)}/{MAX_GALLERY_SIZE}){extra}"
                        if kept_this_frame
                        else f"duplicate pose — turn your head{extra}"
                    )

            # Overlay
            secs_left = max(0.0, deadline - time.monotonic())
            cv2.putText(
                frame,
                f"{args.name}  {status}",
                (24, 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                f"{secs_left:.1f}s left  /  raw frames {raw_frames}  /  kept {len(new_entries)}",
                (24, 78),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (200, 200, 200),
                1,
                cv2.LINE_AA,
            )
            for f in faces:
                x1, y1, x2, y2 = f.bbox.astype(int)
                colour = (0, 200, 0) if kept_this_frame and f is primary else (180, 180, 180)
                cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)

            cv2.imshow("face_id_demo: enroll", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

            now = time.monotonic()
            if now - last_status_log > 2.0:
                log.info(
                    "%.1fs left  raw=%d  kept=%d  status=%s",
                    secs_left,
                    raw_frames,
                    len(new_entries),
                    status,
                )
                last_status_log = now
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if not new_entries:
        print("no embeddings captured — is your face in frame, well-lit, frontal-ish?")
        return 1

    save_gallery(existing + new_entries)
    print(
        f"saved {len(new_entries)} embeddings for {args.name} "
        f"(gallery total: {len(existing) + len(new_entries)})"
    )
    print(f"file: {GALLERY_PATH}")
    return 0


def cmd_detect(args) -> int:
    gallery = load_gallery()
    if not gallery:
        print("gallery is empty — run `enroll` first")
        return 1

    app = make_app()
    cap = open_camera(args.camera)
    log.info(
        "starting live detection (gallery: %d embeddings across %d names)",
        len(gallery),
        len({e.name for e in gallery}),
    )

    last_log = 0.0
    last_t = time.monotonic()
    fps = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            t0 = time.monotonic()
            faces = app.get(frame)
            inference_ms = (time.monotonic() - t0) * 1000

            now = time.monotonic()
            dt = now - last_t
            last_t = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else (1.0 / dt)

            for face in faces:
                x1, y1, x2, y2 = face.bbox.astype(int)
                emb = l2norm(np.asarray(face.normed_embedding, dtype=np.float32))
                name, score = best_match(emb, gallery)
                matched = score >= args.threshold and name
                label = (
                    f"{name}  {score:.2f}"
                    if matched
                    else f"unknown  best={name or '-'} {score:.2f}"
                )
                colour = (0, 200, 0) if matched else (40, 40, 220)
                cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
                cv2.rectangle(frame, (x1, y1 - 36), (x1 + 360, y1), colour, -1)
                cv2.putText(
                    frame,
                    label,
                    (x1 + 8, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

            hud = f"fps {fps:5.1f}  inf {inference_ms:5.1f}ms  thr {args.threshold:.2f}  gallery {len(gallery)}"
            cv2.putText(
                frame,
                hud,
                (24, 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow("face_id_demo: detect (q to quit)", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

            if now - last_log > 1.0:
                log.info("fps=%.1f inference_ms=%.1f faces=%d", fps, inference_ms, len(faces))
                last_log = now
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    enroll = sub.add_parser("enroll", help="capture diverse pose embeddings")
    enroll.add_argument("--name", required=True, help="identity label, e.g. aditya")
    enroll.add_argument("--seconds", type=float, default=15.0)
    enroll.add_argument("--camera", type=int, default=0)
    enroll.add_argument(
        "--append",
        action="store_true",
        help="add to existing entries for this name instead of replacing them",
    )
    enroll.set_defaults(func=cmd_enroll)

    detect = sub.add_parser("detect", help="live label every face")
    detect.add_argument("--camera", type=int, default=0)
    detect.add_argument(
        "--threshold",
        type=float,
        default=SIM_THRESHOLD,
        help=f"cosine sim threshold for a positive match (default {SIM_THRESHOLD})",
    )
    detect.set_defaults(func=cmd_detect)

    stat = sub.add_parser("status", help="print gallery + ORT provider info")
    stat.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
