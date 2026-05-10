"""Tests for the ThirdEye MCP tool surface.

The MCP server exposes four tools for Claude to call:

    list_cameras() -> [{cam_id, t_start, t_end, sample_count}]
    search_people(color_top?, garment_top?, ...) -> [PersonClusterPayload]
    get_track_timeline(cluster_id) -> [{cam_id, ts, thumb (ImageContent)}]
    get_frame(sample_id) -> ImageContent

These tests exercise the tool functions directly (no stdio boot)
against an in-memory SearchEngine so the schemas are pinned. The
ImageContent base64 is verified to round-trip back to readable JPEG
bytes.
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
mcp_types = pytest.importorskip("mcp.types")

from search.core import SearchEngine
from vision_pipeline.track_store import EMBEDDING_DIM, TrackStore

from mcp_server.server import SafeWatchTools


# --- helpers ------------------------------------------------------------


def _norm(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def _write_jpeg(path: Path, color: tuple[int, int, int], size: int = 64) -> None:
    img = np.full((size, size, 3), color, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok, f"could not write {path}"


@pytest.fixture
def tools(tmp_path: Path) -> SafeWatchTools:
    media_root = tmp_path / "media"
    db_path = tmp_path / "tracks.db"

    store = TrackStore(db_path)
    rng = np.random.default_rng(0)
    base_a = _norm(rng.standard_normal(EMBEDDING_DIM))
    base_b = _norm(rng.standard_normal(EMBEDDING_DIM))

    def _add_track(cam: str, local_id: int, t0: float, base: np.ndarray,
                   tags: dict[str, str], color: tuple[int, int, int]) -> int:
        tid = store.upsert_track(cam, local_id, t0, t0 + 5.0,
                                 raw_caption=" ".join(f"{k}={v}" for k, v in tags.items()))
        for i, ts in enumerate((t0, t0 + 2.0, t0 + 4.0)):
            frame_rel = f"{cam}/frame_{local_id}_{i}.jpg"
            thumb_rel = f"{cam}/thumb_{local_id}_{i}.jpg"
            _write_jpeg(media_root / frame_rel, color)
            _write_jpeg(media_root / thumb_rel, color, size=128)
            jit = _norm(base + 0.01 * rng.standard_normal(EMBEDDING_DIM))
            store.insert_sample(tid, ts, frame_rel, thumb_rel, jit, tags)
        return tid

    _add_track("cam_1", 1, 100.0, base_a,
               {"color_top": "red", "garment_top": "hoodie"},
               (40, 40, 200))  # BGR red-ish
    _add_track("cam_2", 1, 130.0, base_a,
               {"color_top": "red", "garment_top": "hoodie"},
               (40, 40, 200))
    _add_track("cam_1", 2, 200.0, base_b,
               {"color_top": "blue", "garment_top": "jacket"},
               (200, 80, 40))

    engine = SearchEngine(store)
    yield SafeWatchTools(engine=engine, media_root=media_root)
    store.close()


# --- list_cameras ------------------------------------------------------


def test_list_cameras_returns_two_cams(tools: SafeWatchTools) -> None:
    out = tools.list_cameras()
    assert isinstance(out, list)
    cam_ids = {c["cam_id"] for c in out}
    assert cam_ids == {"cam_1", "cam_2"}
    for c in out:
        assert {"cam_id", "t_start", "t_end", "sample_count"} <= set(c.keys())


# --- search_people -----------------------------------------------------


def test_search_people_red_hoodie_returns_clusters(tools: SafeWatchTools) -> None:
    payload = tools.search_people(color_top="red", garment_top="hoodie")
    assert "clusters" in payload
    clusters = payload["clusters"]
    assert isinstance(clusters, list)
    assert len(clusters) >= 1
    for c in clusters:
        assert {"cluster_id", "cams_seen", "t_start", "t_end",
                "sample_count", "thumbnail"} <= set(c.keys())


def test_search_people_thumbnails_are_image_content(tools: SafeWatchTools) -> None:
    payload = tools.search_people(color_top="red", garment_top="hoodie")
    for c in payload["clusters"]:
        thumb = c["thumbnail"]
        assert isinstance(thumb, mcp_types.ImageContent)
        # base64 round-trip → real bytes
        raw = base64.b64decode(thumb.data)
        # JPEG SOI marker
        assert raw[:2] == b"\xff\xd8", "thumbnail base64 is not a valid JPEG"


def test_search_people_no_match_returns_empty(tools: SafeWatchTools) -> None:
    payload = tools.search_people(color_top="purple")
    assert payload["clusters"] == []


# --- get_track_timeline ------------------------------------------------


def test_get_track_timeline_ordered_with_images(tools: SafeWatchTools) -> None:
    clusters = tools.search_people(color_top="red",
                                   garment_top="hoodie")["clusters"]
    multi = next(c for c in clusters if len(c["cams_seen"]) >= 2)
    timeline = tools.get_track_timeline(multi["cluster_id"])
    assert isinstance(timeline, list)
    timestamps = [e["ts"] for e in timeline]
    assert timestamps == sorted(timestamps)
    cams = {e["cam_id"] for e in timeline}
    assert {"cam_1", "cam_2"}.issubset(cams)
    # Each entry has an ImageContent thumbnail
    for entry in timeline:
        assert isinstance(entry["thumbnail"], mcp_types.ImageContent)


def test_get_track_timeline_unknown_cluster_raises(tools: SafeWatchTools) -> None:
    with pytest.raises((ValueError, KeyError, LookupError)):
        tools.get_track_timeline("c_does_not_exist_999")


# --- get_frame ---------------------------------------------------------


def test_get_frame_returns_image_content(tools: SafeWatchTools) -> None:
    clusters = tools.search_people(color_top="red",
                                   garment_top="hoodie")["clusters"]
    sample_id = clusters[0]["representative_sample_id"]
    img = tools.get_frame(sample_id)
    assert isinstance(img, mcp_types.ImageContent)
    raw = base64.b64decode(img.data)
    assert raw[:2] == b"\xff\xd8"


def test_get_frame_unknown_sample_raises(tools: SafeWatchTools) -> None:
    with pytest.raises((ValueError, FileNotFoundError, LookupError)):
        tools.get_frame(99999)


# --- thumbnail size guard ---------------------------------------------


def test_thumbnail_size_under_limit(tools: SafeWatchTools) -> None:
    """MCP image content blocks should stay well under ~5MB after base64."""
    payload = tools.search_people(color_top="red", garment_top="hoodie")
    for c in payload["clusters"]:
        # base64 inflates by ~4/3, but we cap thumbnails at 256px JPEG q80
        decoded_size = len(base64.b64decode(c["thumbnail"].data))
        assert decoded_size < 500_000, (
            f"thumbnail {decoded_size} bytes exceeds 500 KB safety budget"
        )
