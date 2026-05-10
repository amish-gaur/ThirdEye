"""HTTP fallback for the MCP demo.

Same logic as the MCP tools, exposed over plain HTTP so a `curl` from
the demo laptop's terminal still works if Claude / wifi dies on stage.

Routes:
    GET  /cameras                          → list_cameras
    GET  /search?color_top=red&...         → search_people
    GET  /timeline/{cluster_id}            → get_track_timeline
    GET  /frame/{sample_id}                → raw JPEG bytes
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from fastapi.testclient import TestClient

from mcp_server.http_fallback import build_app
from mcp_server.server import SafeWatchTools
from search.core import SearchEngine
from vision_pipeline.track_store import EMBEDDING_DIM, TrackStore


def _norm(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def _write_jpeg(path: Path, color: tuple[int, int, int], size: int = 64) -> None:
    img = np.full((size, size, 3), color, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    media_root = tmp_path / "media"
    db_path = tmp_path / "tracks.db"
    store = TrackStore(db_path)
    rng = np.random.default_rng(0)
    base_a = _norm(rng.standard_normal(EMBEDDING_DIM))

    def _add(cam: str, local_id: int, t0: float, color: tuple[int, int, int],
             tags: dict[str, str]) -> int:
        tid = store.upsert_track(cam, local_id, t0, t0 + 5.0,
                                 raw_caption="seed")
        for i, ts in enumerate((t0, t0 + 2.5, t0 + 5.0)):
            frame = f"{cam}/f_{local_id}_{i}.jpg"
            thumb = f"{cam}/t_{local_id}_{i}.jpg"
            _write_jpeg(media_root / frame, color)
            _write_jpeg(media_root / thumb, color, size=128)
            jit = _norm(base_a + 0.01 * rng.standard_normal(EMBEDDING_DIM))
            store.insert_sample(tid, ts, frame, thumb, jit, tags)
        return tid

    _add("cam_1", 1, 100.0, (40, 40, 200),
         {"color_top": "red", "garment_top": "hoodie"})
    _add("cam_2", 1, 130.0, (40, 40, 200),
         {"color_top": "red", "garment_top": "hoodie"})

    engine = SearchEngine(store)
    tools = SafeWatchTools(engine=engine, media_root=media_root)
    app = build_app(tools)
    return TestClient(app)


def test_cameras_route(client: TestClient) -> None:
    r = client.get("/cameras")
    assert r.status_code == 200
    cams = r.json()
    assert {c["cam_id"] for c in cams} == {"cam_1", "cam_2"}


def test_search_route_red_hoodie(client: TestClient) -> None:
    r = client.get("/search", params={"color_top": "red",
                                       "garment_top": "hoodie"})
    assert r.status_code == 200
    payload = r.json()
    assert "clusters" in payload
    assert len(payload["clusters"]) >= 1
    # MCP-shape parity: same keys
    for c in payload["clusters"]:
        assert {"cluster_id", "cams_seen", "t_start",
                "t_end", "sample_count"} <= set(c.keys())
    # HTTP variant returns thumbnails as base64 strings (no ImageContent over JSON)
    for c in payload["clusters"]:
        assert isinstance(c["thumbnail_base64"], str)
        assert len(c["thumbnail_base64"]) > 100


def test_search_route_no_match(client: TestClient) -> None:
    r = client.get("/search", params={"color_top": "purple"})
    assert r.status_code == 200
    assert r.json()["clusters"] == []


def test_timeline_route(client: TestClient) -> None:
    r = client.get("/search", params={"color_top": "red",
                                       "garment_top": "hoodie"})
    cluster_id = r.json()["clusters"][0]["cluster_id"]
    r = client.get(f"/timeline/{cluster_id}")
    assert r.status_code == 200
    timeline = r.json()
    assert isinstance(timeline, list)
    timestamps = [e["ts"] for e in timeline]
    assert timestamps == sorted(timestamps)


def test_timeline_unknown_cluster(client: TestClient) -> None:
    r = client.get("/timeline/c_does_not_exist_999")
    assert r.status_code == 404


def test_frame_route_returns_jpeg(client: TestClient) -> None:
    r = client.get("/search", params={"color_top": "red",
                                       "garment_top": "hoodie"})
    sample_id = r.json()["clusters"][0]["representative_sample_id"]
    r = client.get(f"/frame/{sample_id}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"


def test_frame_route_unknown_sample(client: TestClient) -> None:
    r = client.get("/frame/99999")
    assert r.status_code == 404
