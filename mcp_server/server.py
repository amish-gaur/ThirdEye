"""SafeWatch MCP server — Claude is the UI.

Four tools exposed:

    list_cameras                        → which cams are in this neighborhood
    search_people(color, garment, ...)  → cross-cam person clusters
    get_track_timeline(cluster_id)      → ordered samples for a cluster
    get_frame(sample_id)                → full-res frame for a sample

Thumbnails are 256-px JPEG q80 inline ImageContent blocks so the
results render directly in Claude Desktop / Claude.ai / Claude Code.

The same `SafeWatchTools` object is reused by the FastAPI HTTP
fallback (transport differs, logic is identical).

    .venv/bin/python -m mcp_server.server  # runs over stdio
"""

from __future__ import annotations

import argparse
import base64
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP

from search.core import PersonCluster, SearchEngine
from vision_pipeline.track_store import Sample, TrackStore

# 256 px max edge keeps base64-encoded payloads well under MCP's per-content
# block ceiling and the round-trip latency low.
THUMBNAIL_MAX_EDGE = 256
THUMBNAIL_JPEG_QUALITY = 80


# ----------------------------------------------------------------------
# Tools (logic, no transport)
# ----------------------------------------------------------------------


@dataclass
class SafeWatchTools:
    """Thin adapter from SearchEngine results to MCP-shaped payloads.

    `media_root` is prepended to relative frame_path / thumb_path values
    in the store. Pass an absolute root that contains the frames the
    ingest pipeline wrote.
    """

    engine: SearchEngine
    media_root: Path

    # ----- list_cameras --------------------------------------------------

    def list_cameras(self) -> list[dict[str, Any]]:
        return self.engine.list_cameras()

    # ----- search_people -------------------------------------------------

    def search_people(
        self,
        color_top: str | None = None,
        garment_top: str | None = None,
        color_bottom: str | None = None,
        garment_bottom: str | None = None,
        headwear: str | None = None,
        accessory: str | None = None,
        build: str | None = None,
        gender: str | None = None,
        cam_ids: list[str] | None = None,
        t_min: float | None = None,
        t_max: float | None = None,
    ) -> dict[str, Any]:
        clusters = self.engine.search_people(
            color_top=color_top, garment_top=garment_top,
            color_bottom=color_bottom, garment_bottom=garment_bottom,
            headwear=headwear, accessory=accessory,
            build=build, gender=gender,
            cam_ids=cam_ids, t_min=t_min, t_max=t_max,
        )
        return {
            "clusters": [self._cluster_payload(c) for c in clusters],
            "filter": {
                "color_top": color_top, "garment_top": garment_top,
                "color_bottom": color_bottom, "garment_bottom": garment_bottom,
                "headwear": headwear, "accessory": accessory,
                "build": build, "gender": gender,
                "cam_ids": cam_ids,
                "t_min": t_min, "t_max": t_max,
            },
        }

    # ----- get_track_timeline -------------------------------------------

    def get_track_timeline(self, cluster_id: str) -> list[dict[str, Any]]:
        timeline = self.engine.get_track_timeline(cluster_id)
        if not timeline:
            raise LookupError(f"cluster {cluster_id!r} has no samples")
        return [
            {
                "sample_id": s.id,
                "cam_id": s.cam_id,
                "ts": s.ts,
                "tags": dict(s.tags),
                "thumbnail": self._image_for_sample(s, prefer_thumb=True),
            }
            for s in timeline
        ]

    # ----- get_frame -----------------------------------------------------

    def get_frame(self, sample_id: int) -> mcp_types.ImageContent:
        # Cheapest path: scan the engine's cached embeddings to find which
        # track_id this sample belongs to, then pull from the store.
        # At hackathon scale (~15k samples) this is still fast.
        for tid in {s.track_id for s in self._iter_all_samples()}:
            for s in self.engine.store.list_samples_by_track(tid):
                if s.id == sample_id:
                    return self._image_for_sample(s, prefer_thumb=False)
        raise LookupError(f"sample {sample_id} not found")

    # ----- helpers -------------------------------------------------------

    def _iter_all_samples(self) -> list[Sample]:
        return self.engine.store.search_samples()

    def _cluster_payload(self, cluster: PersonCluster) -> dict[str, Any]:
        rep_sample = next(
            (s for s in cluster.samples
             if s.thumb_path == cluster.representative_thumb_path),
            cluster.samples[0] if cluster.samples else None,
        )
        thumb = (
            self._image_for_sample(rep_sample, prefer_thumb=True)
            if rep_sample is not None
            else _empty_image()
        )
        return {
            "cluster_id": cluster.cluster_id,
            "cams_seen": sorted(cluster.cams_seen),
            "t_start": cluster.t_start,
            "t_end": cluster.t_end,
            "sample_count": len(cluster.samples),
            "track_count": len(cluster.track_ids),
            "representative_sample_id": rep_sample.id if rep_sample else None,
            "thumbnail": thumb,
        }

    def _resolve(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        return p if p.is_absolute() else self.media_root / p

    def _image_for_sample(
        self, sample: Sample, *, prefer_thumb: bool,
    ) -> mcp_types.ImageContent:
        path = self._resolve(
            sample.thumb_path if prefer_thumb else sample.frame_path
        )
        if not path.exists():
            # Fall back to the other variant if one is missing.
            other = self._resolve(
                sample.frame_path if prefer_thumb else sample.thumb_path
            )
            if not other.exists():
                raise FileNotFoundError(
                    f"sample {sample.id}: neither {path} nor {other} on disk"
                )
            path = other
        return _jpeg_to_image_content(path, downscale=prefer_thumb)


# ----------------------------------------------------------------------
# Image utilities
# ----------------------------------------------------------------------


def _jpeg_to_image_content(
    path: Path, *, downscale: bool,
) -> mcp_types.ImageContent:
    """Read an image, optionally resize to ≤THUMBNAIL_MAX_EDGE, return ImageContent."""
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"cv2 could not read {path}")
    if downscale:
        h, w = img.shape[:2]
        m = max(h, w)
        if m > THUMBNAIL_MAX_EDGE:
            scale = THUMBNAIL_MAX_EDGE / m
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(
        ".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, THUMBNAIL_JPEG_QUALITY],
    )
    if not ok:
        raise RuntimeError(f"jpeg encode failed for {path}")
    data_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return mcp_types.ImageContent(
        type="image", data=data_b64, mimeType="image/jpeg",
    )


def _empty_image() -> mcp_types.ImageContent:
    """1×1 black JPEG used when a cluster has no samples on disk."""
    img = np.zeros((1, 1, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:  # pragma: no cover
        raise RuntimeError("could not encode placeholder image")
    return mcp_types.ImageContent(
        type="image",
        data=base64.b64encode(buf.tobytes()).decode("ascii"),
        mimeType="image/jpeg",
    )


# ----------------------------------------------------------------------
# FastMCP wiring
# ----------------------------------------------------------------------


def build_server(tools: SafeWatchTools, name: str = "safewatch") -> FastMCP:
    """Wire `tools` into a FastMCP instance with all four tools exposed."""
    mcp = FastMCP(name)

    @mcp.tool()
    def list_cameras() -> list[dict[str, Any]]:
        """List the cameras with footage in this neighborhood."""
        return tools.list_cameras()

    @mcp.tool()
    def search_people(
        color_top: str | None = None,
        garment_top: str | None = None,
        color_bottom: str | None = None,
        garment_bottom: str | None = None,
        headwear: str | None = None,
        accessory: str | None = None,
        build: str | None = None,
        gender: str | None = None,
        cam_ids: list[str] | None = None,
        t_min: float | None = None,
        t_max: float | None = None,
    ) -> dict[str, Any]:
        """Find people across all cameras matching the given attributes.

        Each cluster is one person observed across one or more cameras.
        Tag values are canonical: color_top in {"red","blue",...},
        garment_top in {"hoodie","jacket","shirt","tshirt","sweater",...}.
        """
        return tools.search_people(
            color_top=color_top, garment_top=garment_top,
            color_bottom=color_bottom, garment_bottom=garment_bottom,
            headwear=headwear, accessory=accessory,
            build=build, gender=gender,
            cam_ids=cam_ids, t_min=t_min, t_max=t_max,
        )

    @mcp.tool()
    def get_track_timeline(cluster_id: str) -> list[dict[str, Any]]:
        """Return the ordered cross-cam samples for a person cluster."""
        return tools.get_track_timeline(cluster_id)

    @mcp.tool()
    def get_frame(sample_id: int) -> mcp_types.ImageContent:
        """Return the full-resolution frame for a single sample."""
        return tools.get_frame(sample_id)

    return mcp


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path,
        default=Path(os.environ.get("SAFEWATCH_DB", "data/tracks.db")),
        help="path to the TrackStore SQLite file",
    )
    parser.add_argument(
        "--media-root", type=Path,
        default=Path(os.environ.get("SAFEWATCH_MEDIA_ROOT", "data/media")),
        help="root for relative frame_path / thumb_path",
    )
    args = parser.parse_args(argv)

    store = TrackStore(args.db)
    engine = SearchEngine(store)
    tools = SafeWatchTools(engine=engine, media_root=args.media_root)
    server = build_server(tools)
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
