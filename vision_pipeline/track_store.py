"""SQLite-backed persistence for cross-camera tracks and ReID samples.

Schema
------
    tracks
        id              INTEGER PRIMARY KEY
        cam_id          TEXT NOT NULL          -- e.g. "cam_1" or a phone token
        local_track_id  INTEGER NOT NULL       -- BYTETrack id within a cam run
        t_start         REAL NOT NULL          -- unix seconds
        t_end           REAL NOT NULL
        raw_caption     TEXT                   -- last Qwen description
        UNIQUE(cam_id, local_track_id)         -- one row per (cam, tracker) lifecycle

    samples
        id              INTEGER PRIMARY KEY
        track_id        INTEGER NOT NULL REFERENCES tracks(id)
        ts              REAL NOT NULL
        frame_path      TEXT NOT NULL          -- full-res frame on disk
        thumb_path      TEXT NOT NULL          -- ≤256px JPEG q80 for MCP/UI
        embedding       BLOB NOT NULL          -- float32 EMBEDDING_DIM bytes
        color_top       TEXT
        garment_top     TEXT
        color_bottom    TEXT
        garment_bottom  TEXT
        headwear        TEXT
        accessory       TEXT
        build           TEXT
        gender          TEXT
        INDEX(track_id, ts)
        INDEX(color_top, garment_top)
        INDEX(ts)

WAL mode is enabled so multiple subprocess writers (one per camera) can
hit the same file without serializing through a Python lock.

The whole file fits in RAM at hackathon scale (15k samples × 2KB row ≈
30MB) so we don't bother with materialized views or vector-search
extensions. `load_embeddings()` returns the entire embedding matrix as
numpy for sub-millisecond cosine search.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

EMBEDDING_DIM = 512
SCHEMA_VERSION = 1

_TAG_FIELDS: tuple[str, ...] = (
    "color_top", "garment_top",
    "color_bottom", "garment_bottom",
    "headwear", "accessory", "build", "gender",
)


@dataclass(frozen=True)
class Track:
    id: int
    cam_id: str
    local_track_id: int
    t_start: float
    t_end: float
    raw_caption: str | None


@dataclass(frozen=True)
class Sample:
    id: int
    track_id: int
    cam_id: str
    ts: float
    frame_path: str
    thumb_path: str
    embedding: np.ndarray
    tags: dict[str, str]


def _ensure_embedding(emb: np.ndarray) -> bytes:
    if not isinstance(emb, np.ndarray):
        raise TypeError("embedding must be numpy.ndarray")
    if emb.shape != (EMBEDDING_DIM,):
        raise ValueError(
            f"embedding must have shape ({EMBEDDING_DIM},), got {emb.shape}"
        )
    if emb.dtype != np.float32:
        emb = emb.astype(np.float32, copy=False)
    return np.ascontiguousarray(emb).tobytes()


def _decode_embedding(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.shape != (EMBEDDING_DIM,):
        raise ValueError(
            f"corrupt embedding blob: expected {EMBEDDING_DIM} float32, "
            f"got {arr.shape}"
        )
    # frombuffer returns read-only views — copy so callers can mutate freely.
    return arr.copy()


class TrackStore:
    """SQLite WAL-mode store for tracks + samples.

    One instance per process. Connection is kept open for the lifetime of
    the instance and serialized through a per-instance threading.Lock so a
    single TrackStore can be shared across threads inside one process.
    Multi-process safety is provided by SQLite WAL itself.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so background threads in the same process
        # can call us; we serialize with our own lock.
        self._conn = sqlite3.connect(
            str(self.path),
            isolation_level=None,        # autocommit, we manage transactions
            check_same_thread=False,
            timeout=30.0,                # block instead of immediately erroring on lock contention
        )
        self._lock = threading.Lock()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=30000")
            self._init_schema(cur)
            cur.close()

    # --- schema --------------------------------------------------------

    def _init_schema(self, cur: sqlite3.Cursor) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
        """)
        cur.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO schema_version(version) VALUES (?)",
                        (SCHEMA_VERSION,))

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id              INTEGER PRIMARY KEY,
                cam_id          TEXT    NOT NULL,
                local_track_id  INTEGER NOT NULL,
                t_start         REAL    NOT NULL,
                t_end           REAL    NOT NULL,
                raw_caption     TEXT,
                UNIQUE(cam_id, local_track_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id              INTEGER PRIMARY KEY,
                track_id        INTEGER NOT NULL REFERENCES tracks(id),
                ts              REAL    NOT NULL,
                frame_path      TEXT    NOT NULL,
                thumb_path      TEXT    NOT NULL,
                embedding       BLOB    NOT NULL,
                color_top       TEXT,
                garment_top     TEXT,
                color_bottom    TEXT,
                garment_bottom  TEXT,
                headwear        TEXT,
                accessory       TEXT,
                build           TEXT,
                gender          TEXT
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_samples_track_ts ON samples(track_id, ts)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_samples_tags "
            "ON samples(color_top, garment_top)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts)")

    # --- introspection -------------------------------------------------

    def tables(self) -> set[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            return {r[0] for r in cur.fetchall()}

    def journal_mode(self) -> str:
        with self._lock:
            cur = self._conn.execute("PRAGMA journal_mode")
            return cur.fetchone()[0]

    # --- writes --------------------------------------------------------

    def upsert_track(
        self,
        cam_id: str,
        local_track_id: int,
        t_start: float,
        t_end: float,
        raw_caption: str | None = None,
    ) -> int:
        """Insert-or-extend a (cam_id, local_track_id) track. Returns row id.

        If the (cam_id, local_track_id) pair already exists, t_end is
        extended to max(existing, new) and raw_caption is replaced when
        non-None — matching how live tracking would update the row as
        the same person is seen for longer.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, t_start, t_end FROM tracks "
                "WHERE cam_id = ? AND local_track_id = ?",
                (cam_id, local_track_id),
            )
            row = cur.fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO tracks(cam_id, local_track_id, t_start, "
                    "t_end, raw_caption) VALUES (?, ?, ?, ?, ?)",
                    (cam_id, local_track_id, t_start, t_end, raw_caption),
                )
                return int(cur.lastrowid)
            track_id, existing_start, existing_end = row
            new_start = min(existing_start, t_start)
            new_end = max(existing_end, t_end)
            if raw_caption is not None:
                self._conn.execute(
                    "UPDATE tracks SET t_start = ?, t_end = ?, "
                    "raw_caption = ? WHERE id = ?",
                    (new_start, new_end, raw_caption, track_id),
                )
            else:
                self._conn.execute(
                    "UPDATE tracks SET t_start = ?, t_end = ? WHERE id = ?",
                    (new_start, new_end, track_id),
                )
            return int(track_id)

    def insert_sample(
        self,
        track_id: int,
        ts: float,
        frame_path: str,
        thumb_path: str,
        embedding: np.ndarray,
        tags: dict[str, str],
    ) -> int:
        blob = _ensure_embedding(embedding)
        cols = ["track_id", "ts", "frame_path", "thumb_path", "embedding"]
        vals: list = [track_id, ts, frame_path, thumb_path, blob]
        for f in _TAG_FIELDS:
            cols.append(f)
            vals.append(tags.get(f))
        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO samples({', '.join(cols)}) VALUES ({placeholders})"
        with self._lock:
            cur = self._conn.execute(sql, vals)
            return int(cur.lastrowid)

    # --- reads ---------------------------------------------------------

    def get_track(self, track_id: int) -> Track | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, cam_id, local_track_id, t_start, t_end, "
                "raw_caption FROM tracks WHERE id = ?",
                (track_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Track(*row)

    def list_samples_by_track(self, track_id: int) -> list[Sample]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT s.id, s.track_id, t.cam_id, s.ts, s.frame_path, "
                "s.thumb_path, s.embedding, "
                + ", ".join(f"s.{f}" for f in _TAG_FIELDS) +
                " FROM samples s JOIN tracks t ON s.track_id = t.id "
                "WHERE s.track_id = ? ORDER BY s.ts",
                (track_id,),
            )
            rows = cur.fetchall()
        return [_row_to_sample(r) for r in rows]

    def search_samples(
        self,
        color_top: str | None = None,
        garment_top: str | None = None,
        color_bottom: str | None = None,
        garment_bottom: str | None = None,
        headwear: str | None = None,
        accessory: str | None = None,
        build: str | None = None,
        gender: str | None = None,
        cam_ids: Sequence[str] | None = None,
        t_min: float | None = None,
        t_max: float | None = None,
        limit: int | None = None,
    ) -> list[Sample]:
        clauses: list[str] = []
        params: list = []
        equality_filters = {
            "s.color_top": color_top,
            "s.garment_top": garment_top,
            "s.color_bottom": color_bottom,
            "s.garment_bottom": garment_bottom,
            "s.headwear": headwear,
            "s.accessory": accessory,
            "s.build": build,
            "s.gender": gender,
        }
        for col, val in equality_filters.items():
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        if cam_ids:
            placeholders = ", ".join(["?"] * len(cam_ids))
            clauses.append(f"t.cam_id IN ({placeholders})")
            params.extend(cam_ids)
        if t_min is not None:
            clauses.append("s.ts >= ?")
            params.append(t_min)
        if t_max is not None:
            clauses.append("s.ts <= ?")
            params.append(t_max)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = f" LIMIT {int(limit)}" if limit else ""
        sql = (
            "SELECT s.id, s.track_id, t.cam_id, s.ts, s.frame_path, "
            "s.thumb_path, s.embedding, "
            + ", ".join(f"s.{f}" for f in _TAG_FIELDS) +
            " FROM samples s JOIN tracks t ON s.track_id = t.id "
            f"{where} ORDER BY s.ts{limit_sql}"
        )
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_sample(r) for r in rows]

    def load_embeddings(self) -> tuple[np.ndarray, list[int], list[int]]:
        """Return (embeddings (N, D), sample_ids, track_ids).

        Used by the search layer at startup / refresh to build the
        in-memory cosine-search matrix. Skip the JOIN with tracks here for
        speed — track_id is on samples directly.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, track_id, embedding FROM samples ORDER BY id"
            )
            rows = cur.fetchall()
        if not rows:
            return (
                np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
                [],
                [],
            )
        sample_ids = [int(r[0]) for r in rows]
        track_ids = [int(r[1]) for r in rows]
        embs = np.stack([_decode_embedding(r[2]) for r in rows], axis=0)
        return embs, sample_ids, track_ids

    # --- lifecycle -----------------------------------------------------

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()


def _row_to_sample(row: Iterable) -> Sample:
    items = list(row)
    sid, track_id, cam_id, ts, frame_path, thumb_path, blob = items[:7]
    tag_values = items[7:]
    tags = {
        f: v for f, v in zip(_TAG_FIELDS, tag_values, strict=True) if v is not None
    }
    return Sample(
        id=int(sid),
        track_id=int(track_id),
        cam_id=str(cam_id),
        ts=float(ts),
        frame_path=str(frame_path),
        thumb_path=str(thumb_path),
        embedding=_decode_embedding(blob),
        tags=tags,
    )


__all__ = [
    "EMBEDDING_DIM",
    "Sample",
    "Track",
    "TrackStore",
]
