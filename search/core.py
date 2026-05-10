"""Core search engine: tag filter + ReID expansion → cross-cam clusters.

```
       ┌─────────────────────────────────────────────────────────┐
       │ search_people(color_top, garment_top, time_range, cams) │
       └──────────────────────────┬──────────────────────────────┘
                                  │
                  ┌───────────────▼───────────────┐
                  │ 1. tag-filter on samples       │
                  │    (color, garment, cam, ts)   │
                  └───────────────┬───────────────┘
                                  │ seed_samples
                  ┌───────────────▼───────────────┐
                  │ 2. group seeds by track_id    │
                  │    each seed_track has a mean │
                  │    embedding                  │
                  └───────────────┬───────────────┘
                                  │ seed_tracks
                  ┌───────────────▼───────────────┐
                  │ 3. for each seed_track:        │
                  │    cosine(seed_mean, all_mean) │
                  │    add tracks ≥ THRESHOLD      │
                  │    → cluster                   │
                  └───────────────┬───────────────┘
                                  │ raw_clusters
                  ┌───────────────▼───────────────┐
                  │ 4. merge overlapping clusters │
                  │    (same track in two seeds)   │
                  └───────────────┬───────────────┘
                                  │
                  ┌───────────────▼───────────────┐
                  │ 5. PersonCluster per cohesive  │
                  │    identity, w/ samples,       │
                  │    cams_seen, time bounds,     │
                  │    representative thumbnail    │
                  └────────────────────────────────┘
```

Threshold tuning: 0.55 separates real cross-cam matches from noise
on imagenet-pretrained OSNet at hackathon scale. Bump to ~0.65 once
ReID-trained weights (Market-1501/MSMT17) replace the imagenet defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from vision_pipeline.track_store import (
    EMBEDDING_DIM,
    Sample,
    TrackStore,
)

SIMILARITY_THRESHOLD = float(os.environ.get("SAFEWATCH_SIM_THRESHOLD", "0.85"))
"""Cosine similarity floor for "same person across cams".

Default 0.85 is tuned to ImageNet-pretrained OSNet defaults, where:
    - same person across cams: ~0.93-0.98
    - different people:        ~0.40-0.65 (high baseline due to
                                            imagenet features all
                                            firing on "person")
Drop to ~0.55-0.65 once ReID-trained weights (MSMT17 / Market-1501)
replace the imagenet defaults — those produce clean
~0.7-0.9 same / ~0.1-0.3 different separation.

Override with the `SAFEWATCH_SIM_THRESHOLD` env var.
"""

MAX_SEED_SAMPLES = 256
"""Cap on tag-filter hits used as seeds; large query results don't need
every sample to drive expansion."""


@dataclass(frozen=True)
class PersonCluster:
    cluster_id: str
    track_ids: tuple[int, ...]
    cams_seen: frozenset[str]
    t_start: float
    t_end: float
    samples: tuple[Sample, ...]
    representative_thumb_path: str

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "track_ids": list(self.track_ids),
            "cams_seen": sorted(self.cams_seen),
            "t_start": self.t_start,
            "t_end": self.t_end,
            "sample_count": len(self.samples),
            "representative_thumb_path": self.representative_thumb_path,
        }


@dataclass
class _ClusterDraft:
    track_ids: set[int] = field(default_factory=set)
    samples: list[Sample] = field(default_factory=list)


class SearchEngine:
    """Read-only search over a populated TrackStore.

    Holds a snapshot of the embedding matrix in RAM for sub-millisecond
    cosine queries. Call `refresh()` after the ingest pipeline writes
    new samples.
    """

    def __init__(
        self,
        store: TrackStore,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self.store = store
        self.similarity_threshold = similarity_threshold
        self._embs: np.ndarray = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        self._sample_ids: list[int] = []
        self._track_ids: list[int] = []
        self._mean_by_track: dict[int, np.ndarray] = {}
        self.refresh()

    # --- ingestion-time hook ------------------------------------------

    def refresh(self) -> None:
        """Reload embeddings + per-track means from the store."""
        embs, sample_ids, track_ids = self.store.load_embeddings()
        self._embs = embs
        self._sample_ids = sample_ids
        self._track_ids = track_ids
        self._mean_by_track = self._compute_means(embs, track_ids)

    @staticmethod
    def _compute_means(
        embs: np.ndarray, track_ids: Sequence[int],
    ) -> dict[int, np.ndarray]:
        means: dict[int, list[np.ndarray]] = {}
        for emb, tid in zip(embs, track_ids):
            means.setdefault(tid, []).append(emb)
        out: dict[int, np.ndarray] = {}
        for tid, vs in means.items():
            mean = np.mean(np.stack(vs, axis=0), axis=0)
            n = np.linalg.norm(mean)
            out[tid] = mean / n if n > 0 else mean
        return out

    # --- public API ----------------------------------------------------

    def list_cameras(self) -> list[dict]:
        """Per-cam time coverage. Used by Claude to ground "what cams exist?"."""
        # Scrape from the samples table: cheaper than another schema layer.
        rows = self.store.search_samples()
        if not rows:
            return []
        per_cam: dict[str, tuple[float, float, int]] = {}
        for s in rows:
            t_min, t_max, n = per_cam.get(s.cam_id, (s.ts, s.ts, 0))
            per_cam[s.cam_id] = (min(t_min, s.ts), max(t_max, s.ts), n + 1)
        return [
            {"cam_id": cam, "t_start": t0, "t_end": t1, "sample_count": n}
            for cam, (t0, t1, n) in sorted(per_cam.items())
        ]

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
        cam_ids: Sequence[str] | None = None,
        t_min: float | None = None,
        t_max: float | None = None,
    ) -> list[PersonCluster]:
        """Find people matching the tag filter, expanded across cams via ReID."""
        seeds = self.store.search_samples(
            color_top=color_top, garment_top=garment_top,
            color_bottom=color_bottom, garment_bottom=garment_bottom,
            headwear=headwear, accessory=accessory,
            build=build, gender=gender,
            cam_ids=cam_ids,
            t_min=t_min, t_max=t_max,
            limit=MAX_SEED_SAMPLES,
        )
        if not seeds:
            return []

        seed_track_ids = {s.track_id for s in seeds}
        seed_means = {
            tid: self._mean_by_track[tid]
            for tid in seed_track_ids
            if tid in self._mean_by_track
        }
        if not seed_means:
            return []

        # Build raw clusters: each seed track becomes the nucleus of a cluster
        # containing every track whose mean cosine clears the threshold.
        all_track_ids = list(self._mean_by_track.keys())
        all_means = np.stack(
            [self._mean_by_track[tid] for tid in all_track_ids], axis=0,
        )
        raw_clusters: list[set[int]] = []
        for seed_tid, seed_mean in seed_means.items():
            sims = all_means @ seed_mean
            members = {
                all_track_ids[i]
                for i, sim in enumerate(sims)
                if float(sim) >= self.similarity_threshold
            }
            members.add(seed_tid)
            raw_clusters.append(members)

        merged = _merge_overlapping(raw_clusters)
        return [self._build_cluster(member_ids) for member_ids in merged]

    def get_track_timeline(self, cluster_id: str) -> list[Sample]:
        """All samples on member tracks of a cluster, sorted by ts.

        Cluster IDs are deterministic — the sorted tuple of member
        track_ids encoded as a hex string. So the caller can pass a
        cluster_id back in a follow-up call without us having to hold
        cluster state between calls.
        """
        track_ids = _decode_cluster_id(cluster_id)
        out: list[Sample] = []
        for tid in track_ids:
            out.extend(self.store.list_samples_by_track(tid))
        out.sort(key=lambda s: s.ts)
        return out

    # --- helpers -------------------------------------------------------

    def _build_cluster(self, member_track_ids: Iterable[int]) -> PersonCluster:
        track_ids = tuple(sorted(member_track_ids))
        samples: list[Sample] = []
        for tid in track_ids:
            samples.extend(self.store.list_samples_by_track(tid))
        samples.sort(key=lambda s: s.ts)
        cams = frozenset(s.cam_id for s in samples)
        t_start = samples[0].ts if samples else 0.0
        t_end = samples[-1].ts if samples else 0.0
        # Representative thumb: middle sample of the longest member track.
        rep = _pick_representative(samples, track_ids)
        return PersonCluster(
            cluster_id=_encode_cluster_id(track_ids),
            track_ids=track_ids,
            cams_seen=cams,
            t_start=t_start,
            t_end=t_end,
            samples=tuple(samples),
            representative_thumb_path=rep,
        )


def _merge_overlapping(clusters: list[set[int]]) -> list[set[int]]:
    """Union-find: merge any clusters sharing at least one track id."""
    merged: list[set[int]] = []
    for c in clusters:
        target_idx: int | None = None
        for i, existing in enumerate(merged):
            if existing & c:
                if target_idx is None:
                    existing |= c
                    target_idx = i
                else:
                    # Cascade: we now span an earlier merged cluster too.
                    merged[target_idx] |= existing
                    merged[i] = set()  # mark for removal
        if target_idx is None:
            merged.append(set(c))
    return [m for m in merged if m]


def _encode_cluster_id(track_ids: tuple[int, ...]) -> str:
    return "c_" + "_".join(str(t) for t in track_ids)


def _decode_cluster_id(cluster_id: str) -> tuple[int, ...]:
    if not cluster_id.startswith("c_"):
        raise ValueError(f"bad cluster_id: {cluster_id!r}")
    parts = cluster_id[2:].split("_")
    return tuple(int(p) for p in parts if p)


def _pick_representative(
    samples: Sequence[Sample], track_ids: tuple[int, ...],
) -> str:
    if not samples:
        return ""
    # Pick the longest member track, then its midpoint sample.
    by_track: dict[int, list[Sample]] = {}
    for s in samples:
        by_track.setdefault(s.track_id, []).append(s)
    longest = max(by_track.values(), key=len)
    return longest[len(longest) // 2].thumb_path


__all__ = [
    "PersonCluster",
    "SearchEngine",
    "SIMILARITY_THRESHOLD",
]
