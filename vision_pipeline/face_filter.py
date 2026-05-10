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
    yaw: float | None = None   # head yaw in degrees, when the embedder reports it
    pitch: float | None = None # head pitch in degrees, when reported


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
    """Default embedder backed by InsightFace ArcFace.

    Defaults to `buffalo_l` (ResNet-50, WebFace600K) which gains ~6 points
    of TAR@FAR=1e-4 over `buffalo_s` on hard / off-angle / low-resolution
    faces typical of porch cameras. Override via the `INSIGHTFACE_MODEL`
    env var if you need the smaller model on a constrained device.

    `apply_clahe` runs Contrast Limited Adaptive Histogram Equalization on
    the L-channel of LAB before detection. This measurably helps backlit
    porch scenes (sun-behind-visitor, hard shadows) without distorting the
    face-recognition embedding distribution.

    Lazy-loaded so importing `face_filter` doesn't pull in onnxruntime."""

    def __init__(
        self,
        model_name: str = "buffalo_l",
        det_size: tuple[int, int] = (640, 640),
        *,
        apply_clahe: bool = True,
    ) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self.apply_clahe = bool(apply_clahe)
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
            # CoreML on Apple Silicon — buffalo_l on the Neural Engine is ~3-5x
            # faster than CPU on M-series, which is the difference between
            # face-detect landing on a moving subject vs missing them entirely.
            # Pattern mirrors scripts/face_id_demo.py:make_app(); ctx_id=0
            # picks the first device, providers picks the runtime. Falling
            # back to CPU silently is fine — InsightFace warns if it does.
            app = FaceAnalysis(
                name=self.model_name,
                allowed_modules=["detection", "recognition"],
                providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
            )
            app.prepare(ctx_id=0, det_size=self.det_size)
            providers_per_model: list[tuple[str, list[str]]] = []
            for model_name, model in app.models.items():
                sess = getattr(model, "session", None)
                if sess is not None:
                    providers_per_model.append((model_name, list(sess.get_providers())))
            log.info(
                "InsightFace %s loaded (det_size=%s) providers=%s",
                self.model_name,
                self.det_size,
                providers_per_model,
            )
            if not any(
                "CoreMLExecutionProvider" in providers
                for _, providers in providers_per_model
            ):
                log.warning(
                    "CoreMLExecutionProvider not active on any model — face filter "
                    "will run on CPU and may miss moving subjects. Check that "
                    "onnxruntime-coreml is installed and importable.",
                )
            self._app = app
            return app

    def detect_and_embed(self, bgr_image: np.ndarray) -> list[FaceEmbedding]:
        app = self._ensure_loaded()
        image = self._maybe_clahe(bgr_image)
        faces = app.get(image)
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
            yaw, pitch = _pose_from_face(face)
            out.append(FaceEmbedding(
                bbox=bbox,
                embedding=embedding,
                det_score=det_score,
                yaw=yaw,
                pitch=pitch,
            ))
        return out

    def _maybe_clahe(self, bgr_image: np.ndarray) -> np.ndarray:
        """Apply CLAHE to the L-channel for backlit / hard-shadow scenes.

        ArcFace was trained on natural images so we keep this conservative
        (clip=2.0, 8x8 grid). Skips silently if cv2 is unavailable so the
        unit-test path that injects a stub embedder doesn't pull in OpenCV.
        """
        if not self.apply_clahe or bgr_image is None or bgr_image.size == 0:
            return bgr_image
        try:
            import cv2  # local import to keep the test stub path cv2-free
        except ImportError:
            return bgr_image
        if bgr_image.ndim != 3 or bgr_image.shape[2] != 3:
            return bgr_image
        lab = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        merged = cv2.merge((l, a, b))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _pose_from_face(face: Any) -> tuple[float | None, float | None]:
    """Extract (yaw, pitch) from an InsightFace Face object if available.

    InsightFace exposes Euler angles via `face.pose = (pitch, yaw, roll)`
    in radians on supported backbones. Returns (None, None) on absence so
    callers can degrade gracefully.
    """
    pose = getattr(face, "pose", None)
    if pose is None:
        return None, None
    try:
        pitch_rad, yaw_rad, _roll = (float(x) for x in pose)
    except (TypeError, ValueError):
        return None, None
    return float(np.degrees(yaw_rad)), float(np.degrees(pitch_rad))


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
        similarity_threshold: float = 0.40,
        min_face_pixels: int = 64,
        min_det_score: float = 0.5,
        max_yaw_degrees: float = 35.0,
        max_pitch_degrees: float = 25.0,
        topk_match: int = 3,
        embedder: FaceEmbedder | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.similarity_threshold = float(similarity_threshold)
        self.min_face_pixels = int(min_face_pixels)
        self.min_det_score = float(min_det_score)
        self.max_yaw_degrees = float(max_yaw_degrees)
        self.max_pitch_degrees = float(max_pitch_degrees)
        self.topk_match = max(1, int(topk_match))
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

    def verdict_per_box(
        self,
        frame_bgr: np.ndarray,
        person_boxes: list[Box],
    ) -> list[PersonVerdict]:
        """Like :meth:`classify_persons` but aligned 1:1 with the input list.

        ``classify_persons`` dedups overlapping YOLO detections and returns
        one verdict per logical person, which is the right semantics for the
        suppression decision. The overlay needs the opposite — every input
        box should get a verdict so we can stamp the matched name onto each
        bounding box. We achieve that here by deduping internally, embedding
        once per unique person, then projecting each input box back to its
        representative verdict via IoU.
        """
        if not person_boxes:
            return []
        deduped = _dedup_overlapping_boxes(list(person_boxes), PERSON_BOX_DEDUP_IOU)
        if not deduped:
            return []
        faces = self._embedder.detect_and_embed(frame_bgr)
        deduped_verdicts: list[tuple[Box, PersonVerdict]] = []
        for box in deduped:
            face = _best_face_for_box(faces, box)
            deduped_verdicts.append((box, self._verdict_for_face(face)))

        out: list[PersonVerdict] = []
        for input_box in person_boxes:
            best_v: PersonVerdict | None = None
            best_iou = -1.0
            for d_box, v in deduped_verdicts:
                iou = _box_iou(input_box, d_box)
                if iou > best_iou:
                    best_iou = iou
                    best_v = v
            out.append(best_v if best_v is not None else PersonVerdict(None, 0.0, "no_face"))
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _verdict_for_face(self, face: FaceEmbedding | None) -> PersonVerdict:
        if face is None:
            return PersonVerdict(None, 0.0, "no_face")
        if _box_short_edge(face.bbox) < self.min_face_pixels:
            return PersonVerdict(None, 0.0, "face_too_small")
        if face.det_score < self.min_det_score:
            return PersonVerdict(None, 0.0, "low_quality")
        if face.yaw is not None and abs(face.yaw) > self.max_yaw_degrees:
            return PersonVerdict(None, 0.0, "extreme_yaw")
        if face.pitch is not None and abs(face.pitch) > self.max_pitch_degrees:
            return PersonVerdict(None, 0.0, "extreme_pitch")
        if not self._known:
            return PersonVerdict(None, 0.0, "unknown")
        best_name, best_sim = self._best_match(face.embedding)
        if best_sim >= self.similarity_threshold:
            return PersonVerdict(best_name, best_sim, "known")
        return PersonVerdict(None, best_sim, "unknown")

    def passes_quality_gate(self, face: FaceEmbedding) -> bool:
        """Whether a detected face is good enough to contribute to identity.

        Used by the track-anchored identity resolver to decide which face
        embeddings to feed into per-track averaging.
        """
        if _box_short_edge(face.bbox) < self.min_face_pixels:
            return False
        if face.det_score < self.min_det_score:
            return False
        if face.yaw is not None and abs(face.yaw) > self.max_yaw_degrees:
            return False
        if face.pitch is not None and abs(face.pitch) > self.max_pitch_degrees:
            return False
        return True

    def match_embedding(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Match an externally-computed (or averaged) embedding against the DB.

        Returns (name_if_match_else_None, best_similarity). Used by the
        track-anchored resolver after it averages embeddings across frames.
        """
        if not self._known:
            return None, 0.0
        best_name, best_sim = self._best_match(np.asarray(embedding, dtype=np.float32))
        if best_sim >= self.similarity_threshold:
            return best_name, best_sim
        return None, best_sim

    def _best_match(self, query: np.ndarray) -> tuple[str, float]:
        """Top-K-mean cosine similarity against every enrolled person.

        Falls back to best-of-1 when an enrolled person has fewer than K
        embeddings. Top-K mean is the IJB-C "template" trick: averaging the
        top K nearest enrolled embeddings is more robust than best-of-1
        because a single outlier enrollment photo can no longer poison the
        decision in either direction.
        """
        best_name = ""
        best_sim = -1.0
        for person in self._known:
            sims = person.embeddings @ query  # both rows are L2-normalized
            k = min(self.topk_match, sims.shape[0])
            if k <= 1:
                top = float(sims.max())
            else:
                # Take the K largest (unsorted) and average — cheaper than full sort.
                topk = np.partition(sims, -k)[-k:]
                top = float(topk.mean())
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
    """Read the JSON face DB; returns an empty list if missing or empty.

    Accepts BOTH schemas so the engine works whether the file came from
    `scripts.face_setup` (production: ``{"people": [{"name", "embeddings"}]}``)
    or `scripts/face_id_demo.py enroll` (demo: ``{"entries": [{"name",
    "embedding"}]}``). The two paths intentionally have different filenames
    so we don't blur the architectural separation, but at LOAD time we
    accept whichever shape the caller pointed at — that lets a single
    pulled checkout work without a manual conversion step.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning("Face DB %s is not valid JSON: %s", p, exc)
        return []
    if not isinstance(raw, dict):
        return []

    # Production schema first.
    if "people" in raw:
        people_raw = raw.get("people", [])
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

    # Demo schema (face_id_demo.py): flat list of {name, embedding} entries.
    # Group by name so the live filter sees one _KnownPerson per identity
    # with all that person's embeddings stacked (which is how match scoring
    # works — best-of-K against a single 2D array per person).
    if "entries" in raw:
        groups: dict[str, list[list[float]]] = {}
        for entry in raw.get("entries", []):
            name = str(entry.get("name", "")).strip()
            emb = entry.get("embedding")
            if not name or not emb:
                continue
            groups.setdefault(name, []).append(list(emb))
        out = []
        for name, embs in groups.items():
            try:
                arr = np.asarray(embs, dtype=np.float32)
            except (TypeError, ValueError):
                log.warning("Skipping malformed demo embeddings for %r in %s", name, p)
                continue
            if arr.ndim != 2 or arr.shape[0] == 0:
                continue
            arr = _l2_normalize(arr)
            out.append(_KnownPerson(name=name, embeddings=arr))
        log.info("Loaded face DB %s in demo-gallery schema (%d people)", p, len(out))
        return out

    return []


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
