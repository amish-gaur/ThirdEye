#!/usr/bin/env python3
"""Replay multiple pre-recorded videos through the cross-camera ingest pipeline.

Each video becomes one camera in the ThirdEye neighborhood. The
script runs them sequentially (avoids GPU contention) and writes
all tracks/samples to a single shared SQLite store + media root,
which the MCP server / HTTP fallback then queries.

    .venv/bin/python -m scripts.replay_multicam \\
        --video cam_1=data/demo/front_door.mp4 \\
        --video cam_2=data/demo/driveway.mp4 \\
        --video cam_3=data/demo/sidewalk.mp4 \\
        --db data/tracks.db \\
        --media-root data/media

After this finishes, run the MCP server (`python -m mcp_server.server
--db data/tracks.db --media-root data/media`) or the HTTP fallback
(`python -m mcp_server.http_fallback --db data/tracks.db --media-root
data/media`) and start asking Claude / curl questions.

Flags:
    --no-qwen       skip captioning (search by ReID similarity only)
    --sample-every-n  embed every Nth frame per track (default 10)
    --yolo-model    YOLO weights (default yolo11n.pt)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vision_pipeline.cross_cam_runner import (
    CrossCamRunner,
    PersonTracker,
    ReIDLike,
    RunnerConfig,
)
from vision_pipeline.track_store import TrackStore

log = logging.getLogger("scripts.replay_multicam")


@dataclass(frozen=True)
class CamSpec:
    cam_id: str
    video_path: Path


TrackerFactory = Callable[[str], PersonTracker]
Captioner = Callable[[int, "Any"], str]  # noqa: F821 -- np.ndarray, but lazy


def parse_video_arg(arg: str) -> CamSpec:
    """Parse a `cam_id=path/to/video.mp4` argument."""
    if "=" not in arg:
        raise ValueError(
            f"--video must be cam_id=path; got {arg!r}"
        )
    cam_id, _, path = arg.partition("=")
    cam_id = cam_id.strip()
    path = path.strip()
    if not cam_id:
        raise ValueError(f"empty cam_id in --video {arg!r}")
    if not path:
        raise ValueError(f"empty path in --video {arg!r}")
    return CamSpec(cam_id=cam_id, video_path=Path(path))


def run_replay(
    specs: list[CamSpec],
    db_path: Path,
    media_root: Path,
    tracker_factory: TrackerFactory,
    reid: ReIDLike,
    captioner: Captioner,
    sample_every_n: int = 10,
) -> dict[str, Any]:
    """Run the replay end-to-end. Returns a summary dict.

    summary = {
        "total_samples": int,
        "per_cam": {cam_id: {"samples": int, "error": str | None}}
    }
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    media_root.mkdir(parents=True, exist_ok=True)
    store = TrackStore(db_path)

    summary: dict[str, Any] = {"total_samples": 0, "per_cam": {}}
    try:
        for spec in specs:
            cam_summary: dict[str, Any] = {"samples": 0, "error": None}
            log.info("==> cam=%s video=%s", spec.cam_id, spec.video_path)
            try:
                tracker = tracker_factory(spec.cam_id)
                runner = CrossCamRunner(
                    cam_id=spec.cam_id,
                    store=store,
                    media_root=media_root,
                    tracker=tracker,
                    reid=reid,
                    captioner=captioner,
                    config=RunnerConfig(sample_every_n=sample_every_n),
                )
                n = runner.run(spec.video_path)
                cam_summary["samples"] = n
                summary["total_samples"] += n
                log.info("    cam=%s wrote %d samples", spec.cam_id, n)
            except FileNotFoundError as exc:
                cam_summary["error"] = f"video not found: {exc}"
                log.warning(
                    "skipping cam=%s: %s", spec.cam_id, cam_summary["error"]
                )
            except Exception as exc:  # keep going for the other cams
                cam_summary["error"] = repr(exc)
                log.exception("cam=%s failed: %s", spec.cam_id, exc)
            summary["per_cam"][spec.cam_id] = cam_summary
    finally:
        store.close()
    return summary


# ----------------------------------------------------------------------
# CLI entrypoint (real wiring — uses YOLO + Qwen)
# ----------------------------------------------------------------------


def _build_real_tracker_factory(
    yolo_model: str, device: str | None,
) -> TrackerFactory:
    """A factory that builds a fresh UltralyticsPersonTracker per cam.

    Per-cam fresh state avoids track-id leakage between videos.
    """
    from vision_pipeline.cross_cam_runner import UltralyticsPersonTracker

    def factory(_cam_id: str) -> PersonTracker:
        return UltralyticsPersonTracker(
            model_path=yolo_model, device=device, confidence=0.4,
        )
    return factory


def _build_captioner(no_qwen: bool, device: str | None) -> Captioner:
    if no_qwen:
        return lambda _tid, _crop: ""
    from vision_pipeline.config import CONFIG
    from vision_pipeline.qwen_captioner import QwenClothingCaptioner
    return QwenClothingCaptioner(
        device=device,
        backend=CONFIG.classifier_backend,
        cloud_model=CONFIG.cloud_classifier_model,
        cloud_max_edge=CONFIG.cloud_classifier_max_edge,
        cloud_jpeg_quality=CONFIG.cloud_classifier_jpeg_quality,
        cloud_timeout_seconds=CONFIG.cloud_classifier_timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video", action="append", required=True,
        help="cam_id=path/to/video.mp4 — repeat for multiple cameras",
    )
    parser.add_argument("--db", type=Path, default=Path("data/tracks.db"))
    parser.add_argument("--media-root", type=Path,
                        default=Path("data/media"))
    parser.add_argument("--sample-every-n", type=int, default=10)
    parser.add_argument("--yolo-model", default="yolo11n.pt")
    parser.add_argument("--device", default=None,
                        help="torch device override (cuda, mps, cpu)")
    parser.add_argument("--no-qwen", action="store_true",
                        help="skip captioning (ReID similarity only)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        specs = [parse_video_arg(v) for v in args.video]
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    from vision_pipeline.reid import ReIDExtractor

    reid = ReIDExtractor(device=args.device)
    captioner = _build_captioner(no_qwen=args.no_qwen, device=args.device)
    tracker_factory = _build_real_tracker_factory(
        yolo_model=args.yolo_model, device=args.device,
    )

    summary = run_replay(
        specs=specs,
        db_path=args.db,
        media_root=args.media_root,
        tracker_factory=tracker_factory,
        reid=reid,
        captioner=captioner,
        sample_every_n=args.sample_every_n,
    )

    print("\n=== ThirdEye replay summary ===")
    for cam_id, info in summary["per_cam"].items():
        if info["error"]:
            print(f"  {cam_id}: ERROR — {info['error']}")
        else:
            print(f"  {cam_id}: {info['samples']} samples")
    print(f"TOTAL: {summary['total_samples']} samples → {args.db}")
    print()
    print("Next: launch the MCP server or HTTP fallback")
    print(f"  .venv/bin/python -m mcp_server.server "
          f"--db {args.db} --media-root {args.media_root}")
    print(f"  .venv/bin/python -m mcp_server.http_fallback "
          f"--db {args.db} --media-root {args.media_root}")

    return 0 if summary["total_samples"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
