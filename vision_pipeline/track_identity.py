"""Track-anchored identity for the face-exclusion path.

The plain :class:`FaceFilter` decides per-frame: is the face visible *now*
known? That's wrong for porch cameras. A friend bends over a package, their
face occludes for ~200 ms (head down, hood, body in front of face), and the
filter flips from ``known`` → ``no_face`` mid-event. The classification path
then fires an alert on someone the system identified two frames earlier.

Every commercial system (Nest, Ring, Wyze, Eufy) avoids this by anchoring
identity on the *track*, not the frame. One clean face read tags the track
ID with a name; the track keeps that name through occlusion until it ends.

This module wraps :class:`FaceFilter` with a per-track cache:

* On every frame we still run face detection on the full image (the filter's
  preferred path — see ``classify_persons`` for why per-crop was rejected).
* For each YOLO+ByteTrack person box, we find the best face whose center
  falls inside the box and feed it into a per-track embedding buffer.
* Once a track accumulates enough quality face reads (or one strongly-
  matching read), the track is *anchored* to a name. Subsequent frames where
  the face is missing or low-quality keep that name as long as the track
  hasn't been idle longer than ``anchor_ttl_seconds``.
* If a face appears that contradicts the anchor at high confidence, we
  invalidate the anchor — handles the rare case where ByteTrack reuses a
  track id across two physically different people.
* Body re-identification (OSNet via :mod:`reid`) is an optional second-stage
  fallback: when face is unavailable for a track, we can still recognize it
  by body shape/clothing if its OSNet embedding is close to a recently
  anchored track. This bridges longer occlusions and short ID switches.

Suppression rule: alert path is gated only when *every* visible track is
anchored to a known person. An empty frame, a single unknown track, or a
track whose anchor expired all keep the gate open.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Protocol

import numpy as np

from .face_filter import (
    FaceEmbedding,
    FaceFilter,
    _best_face_for_box,
    _box_area,
    _l2_normalize,
)

log = logging.getLogger("vision_pipeline.track_identity")


Box = tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Body embedder protocol — kept narrow so tests can inject a fake without
# pulling torchreid. The live engine passes its existing ReIDExtractor.
# ---------------------------------------------------------------------------


class BodyEmbedder(Protocol):
    """Anything that turns a BGR person crop into an L2-normalized embedding."""

    def embed(self, crop_bgr: np.ndarray) -> np.ndarray: ...


# ---------------------------------------------------------------------------
# Per-track state + per-frame verdict
# ---------------------------------------------------------------------------


@dataclass
class TrackIdentity:
    """What the resolver currently believes about one track id."""

    track_id: int
    name: str | None = None
    anchored_at: float = 0.0
    last_seen_at: float = 0.0
    # Sims/counts feed the "did we see this person well enough yet?" decision.
    face_match_count: int = 0
    last_face_similarity: float = 0.0
    # Body embedding snapshot taken at anchor time, used for ReID fallback.
    body_embedding: np.ndarray | None = None
    # Recent quality-passed face embeddings; averaged for robust matching.
    embedding_buffer: deque[np.ndarray] = field(
        default_factory=lambda: deque(maxlen=5)
    )

    @property
    def is_anchored(self) -> bool:
        return self.name is not None


@dataclass(frozen=True)
class TrackVerdict:
    """Per-track decision returned by the resolver this frame."""

    track_id: int | None
    name: str | None
    similarity: float
    reason: str  # "anchored" | "freshly_anchored" | "body_match" | "unknown" | "no_face" | "no_track" | "low_quality"

    @property
    def is_known(self) -> bool:
        return self.name is not None


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


# How many quality face reads we need before anchoring on a *moderate* sim.
# A single strongly-matching read (>= STRONG_ANCHOR_SIM) anchors immediately.
DEFAULT_ANCHOR_MIN_FRAMES = 2
DEFAULT_STRONG_ANCHOR_SIM = 0.55
DEFAULT_BODY_REID_THRESHOLD = 0.70  # OSNet cosine, fairly strict
DEFAULT_ANCHOR_TTL_SECONDS = 300.0  # 5 min keeps an identity through breaks
DEFAULT_TRACK_GC_SECONDS = 600.0    # forget tracks unseen for 10 min


class TrackIdentityResolver:
    """Wrap :class:`FaceFilter` so identity is anchored per track id."""

    def __init__(
        self,
        face_filter: FaceFilter,
        *,
        body_embedder: BodyEmbedder | None = None,
        anchor_ttl_seconds: float = DEFAULT_ANCHOR_TTL_SECONDS,
        anchor_min_frames: int = DEFAULT_ANCHOR_MIN_FRAMES,
        strong_anchor_similarity: float = DEFAULT_STRONG_ANCHOR_SIM,
        body_reid_threshold: float = DEFAULT_BODY_REID_THRESHOLD,
        track_gc_seconds: float = DEFAULT_TRACK_GC_SECONDS,
    ) -> None:
        self.face_filter = face_filter
        self.body_embedder = body_embedder
        self.anchor_ttl_seconds = float(anchor_ttl_seconds)
        self.anchor_min_frames = max(1, int(anchor_min_frames))
        self.strong_anchor_similarity = float(strong_anchor_similarity)
        self.body_reid_threshold = float(body_reid_threshold)
        self.track_gc_seconds = float(track_gc_seconds)
        self._tracks: dict[int, TrackIdentity] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Forget every track. Useful between unrelated camera sessions."""
        self._tracks.clear()

    @property
    def anchored_tracks(self) -> dict[int, TrackIdentity]:
        """Snapshot of currently-anchored tracks (read-only view)."""
        return {tid: t for tid, t in self._tracks.items() if t.is_anchored}

    def all_known(
        self,
        frame_bgr: np.ndarray,
        persons: Iterable[tuple[int | None, Box]],
        *,
        now: float | None = None,
    ) -> tuple[bool, list[TrackVerdict]]:
        """Suppression contract identical to :meth:`FaceFilter.all_known`.

        ``persons`` is an iterable of ``(track_id, box)`` tuples — the track
        id is what makes the resolver work; pass ``None`` for tracks the
        backend hasn't confirmed yet (those degrade to per-frame matching).

        Returns ``(suppress, per_track_verdicts)``. ``suppress`` is True iff
        every person box resolves to a known identity.
        """
        if now is None:
            now = time.monotonic()

        person_list = list(persons)
        if not person_list:
            # Still run GC so dropped tracks don't pile up during quiet periods.
            self._gc(now)
            return False, []

        # Run face detection ONCE per frame (the filter's design: avoids the
        # tiny-face / overlapping-crop failure modes documented in face_filter).
        faces = self.face_filter._embedder.detect_and_embed(frame_bgr)
        verdicts: list[TrackVerdict] = []
        for track_id, box in person_list:
            verdicts.append(self._resolve_one(track_id, box, faces, frame_bgr, now))

        self._gc(now)

        suppress = bool(verdicts) and all(v.is_known for v in verdicts)
        return suppress, verdicts

    # ------------------------------------------------------------------
    # Per-track resolution
    # ------------------------------------------------------------------

    def _resolve_one(
        self,
        track_id: int | None,
        box: Box,
        faces: list[FaceEmbedding],
        frame_bgr: np.ndarray,
        now: float,
    ) -> TrackVerdict:
        face = _best_face_for_box(faces, box)

        # Tracks without an id can't be anchored — fall through to the
        # plain face filter contract for the current frame only.
        if track_id is None:
            return self._stateless_verdict(face)

        track = self._tracks.get(track_id)
        if track is None:
            track = TrackIdentity(track_id=track_id)
            self._tracks[track_id] = track
        track.last_seen_at = now

        # Step 1: feed any quality face read into the per-track buffer.
        usable_face = face if face is not None and self.face_filter.passes_quality_gate(face) else None

        # Step 1.5: detect identity flips on the *raw* embedding before averaging.
        # The averaged buffer mixes embeddings from before and after a flip,
        # which hides genuine ByteTrack id reuse — so we probe the raw frame
        # match against the current anchor and reset state if they disagree
        # at high confidence.
        if usable_face is not None and track.is_anchored:
            raw_name, raw_sim = self.face_filter.match_embedding(
                np.asarray(usable_face.embedding, dtype=np.float32)
            )
            if (
                raw_name is not None
                and raw_name != track.name
                and raw_sim >= self.strong_anchor_similarity
            ):
                log.warning(
                    "Track %d identity flipped %s -> %s (raw sim=%.2f); re-anchoring.",
                    track_id, track.name, raw_name, raw_sim,
                )
                track.name = None
                track.anchored_at = 0.0
                track.body_embedding = None
                track.embedding_buffer.clear()
                track.face_match_count = 0

        if usable_face is not None:
            track.embedding_buffer.append(np.asarray(usable_face.embedding, dtype=np.float32))

        # Step 2: try to (re-)anchor from current evidence.
        if usable_face is not None:
            avg = _averaged_embedding(track.embedding_buffer)
            name, sim = self.face_filter.match_embedding(avg)
            if name is not None:
                track.last_face_similarity = sim
                track.face_match_count += 1
                if not track.is_anchored:
                    if (
                        sim >= self.strong_anchor_similarity
                        or track.face_match_count >= self.anchor_min_frames
                    ):
                        track.name = name
                        track.anchored_at = now
                        track.body_embedding = self._maybe_body_embedding(frame_bgr, box)
                        return TrackVerdict(track_id, name, sim, "freshly_anchored")
                else:
                    # Refresh body embedding occasionally so clothing changes
                    # within the same continuous track don't strand us.
                    if track.body_embedding is None:
                        track.body_embedding = self._maybe_body_embedding(frame_bgr, box)
                    return TrackVerdict(track_id, track.name, sim, "anchored")
            else:
                # Quality face but no DB match — keep any prior anchor; the
                # raw-embedding conflict probe above already handled flips.
                track.last_face_similarity = sim

        # Step 3: still anchored from a previous frame?
        if track.is_anchored:
            if (now - track.anchored_at) <= self.anchor_ttl_seconds:
                return TrackVerdict(track_id, track.name, track.last_face_similarity, "anchored")
            # Anchor expired; drop it but allow body-ReID below to recover.
            track.name = None
            track.anchored_at = 0.0

        # Step 4: body-ReID fallback — match against recently anchored tracks.
        body_match = self._body_reid_match(frame_bgr, box, now, exclude_track_id=track_id)
        if body_match is not None:
            name, sim = body_match
            track.name = name
            track.anchored_at = now
            track.face_match_count = max(track.face_match_count, 1)
            return TrackVerdict(track_id, name, sim, "body_match")

        # Step 5: unknown.
        if face is None:
            return TrackVerdict(track_id, None, 0.0, "no_face")
        if usable_face is None:
            return TrackVerdict(track_id, None, 0.0, "low_quality")
        return TrackVerdict(track_id, None, track.last_face_similarity, "unknown")

    # ------------------------------------------------------------------
    # Body re-identification helpers
    # ------------------------------------------------------------------

    def _maybe_body_embedding(
        self, frame_bgr: np.ndarray, box: Box
    ) -> np.ndarray | None:
        if self.body_embedder is None:
            return None
        crop = _crop_bgr(frame_bgr, box)
        if crop is None or crop.size == 0:
            return None
        try:
            emb = self.body_embedder.embed(crop)
        except Exception:
            log.exception("Body embedder failed; continuing without ReID this frame.")
            return None
        return _l2_normalize(np.asarray(emb, dtype=np.float32))

    def _body_reid_match(
        self,
        frame_bgr: np.ndarray,
        box: Box,
        now: float,
        *,
        exclude_track_id: int | None,
    ) -> tuple[str, float] | None:
        if self.body_embedder is None:
            return None
        anchored = [
            t for tid, t in self._tracks.items()
            if t.is_anchored
            and t.body_embedding is not None
            and tid != exclude_track_id
            and (now - t.anchored_at) <= self.anchor_ttl_seconds
        ]
        if not anchored:
            return None
        query = self._maybe_body_embedding(frame_bgr, box)
        if query is None:
            return None
        best: tuple[str, float] | None = None
        for t in anchored:
            sim = float(np.dot(t.body_embedding, query))
            if sim >= self.body_reid_threshold and (best is None or sim > best[1]):
                best = (t.name or "", sim)
        return best

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _stateless_verdict(self, face: FaceEmbedding | None) -> TrackVerdict:
        if face is None:
            return TrackVerdict(None, None, 0.0, "no_face")
        verdict = self.face_filter._verdict_for_face(face)
        return TrackVerdict(None, verdict.name, verdict.similarity, verdict.reason)

    def _gc(self, now: float) -> None:
        # Drop tracks that haven't been seen recently so memory stays bounded.
        stale = [tid for tid, t in self._tracks.items() if (now - t.last_seen_at) > self.track_gc_seconds]
        for tid in stale:
            del self._tracks[tid]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _averaged_embedding(buffer: deque[np.ndarray]) -> np.ndarray:
    """L2-normalized mean of buffered embeddings (latest if just one)."""
    if len(buffer) == 1:
        return np.asarray(buffer[0], dtype=np.float32)
    stacked = np.stack([np.asarray(e, dtype=np.float32) for e in buffer], axis=0)
    mean = stacked.mean(axis=0)
    return _l2_normalize(mean)


def _crop_bgr(frame_bgr: np.ndarray, box: Box) -> np.ndarray | None:
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    h, w = frame_bgr.shape[:2]
    x1 = max(0, int(round(box[0])))
    y1 = max(0, int(round(box[1])))
    x2 = min(w, int(round(box[2])))
    y2 = min(h, int(round(box[3])))
    if x2 <= x1 or y2 <= y1:
        return None
    return frame_bgr[y1:y2, x1:x2]


__all__ = [
    "BodyEmbedder",
    "TrackIdentity",
    "TrackIdentityResolver",
    "TrackVerdict",
]


# Silence "unused" warnings for re-exports we use only in the resolver tests.
_ = (_box_area,)
