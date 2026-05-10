"""Face-recognition exclusion layer for the vision pipeline.

A FaceFilter loads enrolled family-member embeddings from disk and decides,
for each YOLO person box, whether the visible face matches a known person.
The engine consults the filter *before* firing a Qwen classification: if every
candidate person is recognized as family, the classification is suppressed.

Design notes
------------
* The embedder is pluggable. The default implementation wraps InsightFace
  (`buffalo_s`), but tests inject a deterministic stub so they don't need
  the heavy ONNX runtime.
* Face detection runs ONCE on the full frame per call — not on each YOLO crop.
  This matches the enrollment script's path and avoids two failure modes:
  (a) tiny faces inside a tight YOLO box being lost to scale, and
  (b) the wrong face inside an overlapping multi-detection.
* Overlapping YOLO person boxes (IoU >= 0.5) are deduplicated to one logical
  person. YOLO often emits 4-6 overlapping detections of a single person; we
  only want one verdict per actual person.
* Embeddings are L2-normalized; matching uses cosine similarity.
* Fail-open: if no face overlaps the person box, or the face is too small,
  the person is treated as UNKNOWN. We never *whitelist* on negative evidence;
  only positive matches suppress.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

log = logging.getLogger("vision_pipeline.face_filter")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels


@dataclass(frozen=True)
class FaceEmbedding:
    """A face detected by the embedder."""
    bbox: Box                  # box in the frame's coordinate frame
    embedding: np.ndarray      # L2-normalized float32 vector
    det_score: float = 1.0     # face-detector confidence


@dataclass(frozen=True)
class FaceMatch:
    """Result of comparing one face against the family database."""
    name: str
    similarity: float


@dataclass(frozen=True)
class PersonVerdict:
    """Per-person decision returned by the filter."""
    name: str | None       # known family member, or None
    similarity: float      # best similarity seen (0.0 if no face / no match)
    reason: str            # short tag for logging: "known" | "unknown" | "no_face" | "face_too_small" | "disabled"

    @property
    def is_known(self) -> bool:
        return self.name is not None


@dataclass
class _KnownPerson:
    name: str
    embeddings: np.ndarray  # shape (N, D), each row L2-normalized


# ---------------------------------------------------------------------------
# Embedder protocol + default InsightFace implementation
# ---------------------------------------------------------------------------


class FaceEmbedder(Protocol):
    """Pluggable face detector + embedder.

    Implementations take a BGR image (numpy uint8 HxWx3) and return zero or
    more FaceEmbedding objects with L2-normalized embeddings."""

    def detect_and_embed(self, bgr_image: np.ndarray) -> list[FaceEmbedding]:
        ...


class InsightFaceEmbedder:
    """Default embedder backed by InsightFace `buffalo_s` (ArcFace).

    Lazy-loaded so importing `face_filter` doesn't pull in onnxruntime."""

    def __init__(
        self,
        model_name: str = "buffalo_s",
        det_size: tuple[int, int] = (640, 640),
    ) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self._app: Any | None = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> Any:
        if self._app is not None:
            return self._app
        with self._lock:
            if self._app is not None:
                return self._app
            try:
                from insightface.app import FaceAnalysis  # type: ignore
            except ImportError as exc:  # pragma: no cover - exercised only on real installs
                raise RuntimeError(
                    "insightface is not installed. Add `insightface` and "
                    "`onnxruntime` to your environment to enable the face "
                    "filter, or set FACE_FILTER_ENABLED=false."
                ) from exc
            app = FaceAnalysis(name=self.model_name, allowed_modules=["detection", "recognition"])
            # ctx_id=-1 selects CPU; ONNXRuntime will pick the best EP available.
            app.prepare(ctx_id=-1, det_size=self.det_size)
            self._app = app
            log.info(
                "InsightFace %s loaded (det_size=%s)", self.model_name, self.det_size
            )
            return app

    def detect_and_embed(self, bgr_image: np.ndarray) -> list[FaceEmbedding]:
        app = self._ensure_loaded()
        faces = app.get(bgr_image)
        out: list[FaceEmbedding] = []
        for face in faces:
            embedding = getattr(face, "normed_embedding", None)
            if embedding is None:
                embedding = getattr(face, "embedding", None)
                if embedding is None:
                    continue
                embedding = _l2_normalize(np.asarray(embedding, dtype=np.float32))
            else:
                embedding = np.asarray(embedding, dtype=np.float32)
            bbox = tuple(float(v) for v in face.bbox.astype(float))
            det_score = float(getattr(face, "det_score", 1.0))
            out.append(FaceEmbedding(bbox=bbox, embedding=embedding, det_score=det_score))
        return out


# ---------------------------------------------------------------------------
# FaceFilter
# ---------------------------------------------------------------------------


PERSON_BOX_DEDUP_IOU = 0.5  # YOLO multi-detections of one person collapse here


class FaceFilter:
    """Family-face exclusion layer used by the engine."""

    DB_VERSION = 1

    def __init__(
        self,
        *,
        db_path: str | Path,
        similarity_threshold: float = 0.45,
        min_face_pixels: int = 40,
        embedder: FaceEmbedder | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.similarity_threshold = float(similarity_threshold)
        self.min_face_pixels = int(min_face_pixels)
        self._embedder = embedder if embedder is not None else InsightFaceEmbedder()
        self._known: list[_KnownPerson] = load_database(self.db_path)
        if not self._known:
            log.warning(
                "Face DB at %s is empty; filter will treat every person as unknown.",
                self.db_path,
            )
        else:
            log.info(
                "Loaded face DB %s with %d people, %d total embeddings.",
                self.db_path,
                len(self._known),
                sum(len(p.embeddings) for p in self._known),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enrolled_names(self) -> list[str]:
        return [p.name for p in self._known]

    def identify_crop(self, crop_bgr: np.ndarray) -> PersonVerdict:
        """Detect a face in a single image and return a verdict.

        Used by the enrollment / debug paths. The live engine prefers the
        full-frame :py:meth:`classify_persons` because it dedupes YOLO
        multi-detections.
        """
        if crop_bgr is None or crop_bgr.size == 0:
            return PersonVerdict(None, 0.0, "no_face")

        faces = self._embedder.detect_and_embed(crop_bgr)
        if not faces:
            return PersonVerdict(None, 0.0, "no_face")
        face = max(faces, key=lambda f: _box_area(f.bbox))
        return self._verdict_for_face(face)

    def classify_persons(
        self,
        frame_bgr: np.ndarray,
        person_boxes: Iterable[Box],
    ) -> list[PersonVerdict]:
        """Run face detection on the full frame and produce one verdict per
        unique person box.

        Person boxes that overlap (IoU >= 0.5) collapse to a single logical
        person — YOLO routinely emits 4-6 overlapping detections for one body
        and we want one verdict per body, not per box.
        """
        deduped = _dedup_overlapping_boxes(list(person_boxes), PERSON_BOX_DEDUP_IOU)
        if not deduped:
            return []

        faces = self._embedder.detect_and_embed(frame_bgr)
        verdicts: list[PersonVerdict] = []
        for box in deduped:
            face = _best_face_for_box(faces, box)
            verdicts.append(self._verdict_for_face(face))
        return verdicts

    def all_known(
        self,
        frame_bgr: np.ndarray,
        person_boxes: Iterable[Box],
        *,
        now: float | None = None,  # kept for backward compat with callers
    ) -> tuple[bool, list[PersonVerdict]]:
        """Return (suppress?, per-person verdicts).

        suppress is True iff every UNIQUE person in the frame matches a known
        family member. Returns (False, []) when no person boxes are supplied.
        """
        del now  # unused — kept so engine.py doesn't have to change signatures
        verdicts = self.classify_persons(frame_bgr, person_boxes)
        if not verdicts:
            return False, []
        suppress = all(v.is_known for v in verdicts)
        return suppress, verdicts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _verdict_for_face(self, face: FaceEmbedding | None) -> PersonVerdict:
        if face is None:
            return PersonVerdict(None, 0.0, "no_face")
        if _box_short_edge(face.bbox) < self.min_face_pixels:
            return PersonVerdict(None, 0.0, "face_too_small")
        if not self._known:
            return PersonVerdict(None, 0.0, "unknown")
        best_name, best_sim = self._best_match(face.embedding)
        if best_sim >= self.similarity_threshold:
            return PersonVerdict(best_name, best_sim, "known")
        return PersonVerdict(None, best_sim, "unknown")

    def _best_match(self, query: np.ndarray) -> tuple[str, float]:
        """Cosine similarity against every enrolled embedding."""
        best_name = ""
        best_sim = -1.0
        for person in self._known:
            sims = person.embeddings @ query  # both rows are L2-normalized
            top = float(sims.max())
            if top > best_sim:
                best_sim = top
                best_name = person.name
        return best_name, max(0.0, best_sim)

    def all_match_scores(self, query: np.ndarray) -> dict[str, float]:
        """Best similarity to each enrolled person — used by the debug script."""
        out: dict[str, float] = {}
        for person in self._known:
            sims = person.embeddings @ query
            out[person.name] = float(sims.max())
        return out


# ---------------------------------------------------------------------------
# Database I/O
# ---------------------------------------------------------------------------


def load_database(path: str | Path) -> list[_KnownPerson]:
    """Read the JSON face DB; returns an empty list if missing or empty."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning("Face DB %s is not valid JSON: %s", p, exc)
        return []
    people_raw = raw.get("people", []) if isinstance(raw, dict) else []
    out: list[_KnownPerson] = []
    for entry in people_raw:
        name = str(entry.get("name", "")).strip()
        embeddings_raw = entry.get("embeddings", [])
        if not name or not embeddings_raw:
            continue
        try:
            arr = np.asarray(embeddings_raw, dtype=np.float32)
        except (TypeError, ValueError):
            log.warning("Skipping malformed embeddings for %r in %s", name, p)
            continue
        if arr.ndim != 2 or arr.shape[0] == 0:
            continue
        arr = _l2_normalize(arr)
        out.append(_KnownPerson(name=name, embeddings=arr))
    return out


def save_database(path: str | Path, people: dict[str, list[np.ndarray]]) -> None:
    """Write a face DB to disk.

    `people` maps name -> list of L2-normalized embedding vectors. Existing
    entries for the same name are merged (extended, not replaced).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    existing = {pp.name: pp.embeddings for pp in load_database(p)}
    for name, vectors in people.items():
        new = np.stack([_l2_normalize(np.asarray(v, dtype=np.float32)) for v in vectors])
        if name in existing:
            existing[name] = np.concatenate([existing[name], new], axis=0)
        else:
            existing[name] = new

    out = {
        "version": FaceFilter.DB_VERSION,
        "people": [
            {"name": name, "embeddings": embs.tolist()}
            for name, embs in existing.items()
        ],
    }
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _l2_normalize(arr: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 1:
        norm = float(np.linalg.norm(arr))
        return arr / (norm + eps)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / (norms + eps)


def _box_area(box: Box) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _box_short_edge(box: Box) -> float:
    x1, y1, x2, y2 = box
    return min(max(0.0, x2 - x1), max(0.0, y2 - y1))


def _box_center(box: Box) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) * 0.5, (y1 + y2) * 0.5)


def _box_iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    a_area = _box_area(a)
    b_area = _box_area(b)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / union


def _dedup_overlapping_boxes(boxes: list[Box], iou_threshold: float) -> list[Box]:
    """Greedy de-duplication: keep the first box per group of overlaps.

    YOLO multi-detection emits 4-6 boxes per body. Without deduping, the face
    filter's "all_known" check is impossible to satisfy because only one of
    those boxes contains the actual face — the others trivially fail.
    """
    kept: list[Box] = []
    for box in boxes:
        if any(_box_iou(box, k) >= iou_threshold for k in kept):
            continue
        kept.append(box)
    return kept


def _best_face_for_box(faces: list[FaceEmbedding], person_box: Box) -> FaceEmbedding | None:
    """Return the largest face whose center falls inside the person box.

    None if no face center is inside the person box.
    """
    px1, py1, px2, py2 = person_box
    candidates: list[FaceEmbedding] = []
    for face in faces:
        cx, cy = _box_center(face.bbox)
        if px1 <= cx <= px2 and py1 <= cy <= py2:
            candidates.append(face)
    if not candidates:
        return None
    return max(candidates, key=lambda f: _box_area(f.bbox))
