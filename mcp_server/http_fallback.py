"""FastAPI HTTP transport for the SafeWatch search backend.

Same logic as the MCP tools (`SafeWatchTools`), exposed over HTTP so a
plain `curl` from the demo laptop still works if Claude / wifi dies.

Intentionally minimal: four routes, JSON in / JSON or JPEG out.
Thumbnails are base64-encoded strings (JSON-friendly) instead of MCP's
ImageContent dataclass.

    .venv/bin/python -m mcp_server.http_fallback --port 8001
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from mcp_server.server import SafeWatchTools
from search.core import SearchEngine
from vision_pipeline.track_store import TrackStore


def build_app(tools: SafeWatchTools) -> FastAPI:
    app = FastAPI(title="SafeWatch HTTP fallback")

    @app.get("/cameras")
    def cameras() -> list[dict[str, Any]]:
        return tools.list_cameras()

    @app.get("/search")
    def search(
        color_top: str | None = None,
        garment_top: str | None = None,
        color_bottom: str | None = None,
        garment_bottom: str | None = None,
        headwear: str | None = None,
        accessory: str | None = None,
        build: str | None = None,
        gender: str | None = None,
        cam_ids: list[str] | None = Query(default=None),
        t_min: float | None = None,
        t_max: float | None = None,
    ) -> dict[str, Any]:
        payload = tools.search_people(
            color_top=color_top, garment_top=garment_top,
            color_bottom=color_bottom, garment_bottom=garment_bottom,
            headwear=headwear, accessory=accessory,
            build=build, gender=gender,
            cam_ids=cam_ids, t_min=t_min, t_max=t_max,
        )
        # Strip MCP ImageContent objects (not JSON-serializable) and
        # re-attach thumbnails as base64 strings.
        json_clusters = []
        for c in payload["clusters"]:
            thumb = c.pop("thumbnail")
            json_clusters.append({**c, "thumbnail_base64": thumb.data})
        return {"clusters": json_clusters, "filter": payload["filter"]}

    @app.get("/timeline/{cluster_id}")
    def timeline(cluster_id: str) -> list[dict[str, Any]]:
        try:
            entries = tools.get_track_timeline(cluster_id)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        out: list[dict[str, Any]] = []
        for e in entries:
            thumb = e.pop("thumbnail")
            out.append({**e, "thumbnail_base64": thumb.data})
        return out

    @app.get("/frame/{sample_id}")
    def frame(sample_id: int) -> Response:
        try:
            img = tools.get_frame(sample_id)
        except (LookupError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return Response(
            content=base64.b64decode(img.data),
            media_type="image/jpeg",
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path,
        default=Path(os.environ.get("SAFEWATCH_DB", "data/tracks.db")),
    )
    parser.add_argument(
        "--media-root", type=Path,
        default=Path(os.environ.get("SAFEWATCH_MEDIA_ROOT", "data/media")),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)

    import uvicorn

    store = TrackStore(args.db)
    engine = SearchEngine(store)
    tools = SafeWatchTools(engine=engine, media_root=args.media_root)
    app = build_app(tools)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
