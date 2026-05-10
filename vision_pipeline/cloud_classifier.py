"""Anthropic-Claude-backed VLM backend for the vision pipeline.

Mirrors the interface used by the local Qwen path so the engine and the
cross-camera captioner can pick a backend at boot time via the
`CLASSIFIER_BACKEND=cloud` env var.

Why this exists:
- Qwen2-VL-2B is ~5GB of weights and needs Apple Silicon MPS or NVIDIA
  CUDA at fp16. Teammates on Intel laptops or weak GPUs cannot run it.
- The rule-based `PackageTheftTracker` already gates when classification
  fires, so a cloud round-trip on each real event is cheap (a handful of
  cents per day in a normal deployment).
- The existing JSON parser in `vision_pipeline.events` is permissive
  (strips code fences, tolerates smart quotes, validates fields) — we
  just need to hand it Claude's text output verbatim.

Two surfaces are exposed:

* ``CloudHeavyClassifier``  — multi-frame VLM call with the heavy
  ``VISION_LANGUAGE_PROMPT`` from ``events.py``. Returns the raw model
  text so the existing ``evaluate_classifier_output`` parser handles it.

* ``CloudClothingDescriber`` — single-crop call with the lightweight
  ``CAPTION_PROMPT`` from ``qwen_captioner.py``. Returns a short
  free-form clothing description for cross-cam search.

Both lazy-import ``anthropic`` and ``cv2`` so importing this module is
free even on machines without those packages installed.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

log = logging.getLogger("vision_pipeline.cloud_classifier")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_EDGE = 768
DEFAULT_JPEG_QUALITY = 80
DEFAULT_HEAVY_MAX_TOKENS = 400
DEFAULT_CAPTION_MAX_TOKENS = 80
DEFAULT_TIMEOUT_SECONDS = 12.0


def _encode_jpeg_b64(
    frame_bgr: np.ndarray,
    *,
    max_edge: int = DEFAULT_MAX_EDGE,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> str:
    """Downscale to ``max_edge`` longest side, JPEG-encode, base64 wrap.

    Anthropic accepts up to ~5MB per image but smaller is faster and
    cheaper. 768px on the long edge is enough resolution for clothing
    color + carryable identification and keeps each call sub-150KB.
    """
    import cv2

    if frame_bgr is None or not isinstance(frame_bgr, np.ndarray):
        raise ValueError("frame_bgr must be a numpy ndarray")
    if frame_bgr.size == 0:
        raise ValueError("frame_bgr is empty")

    h, w = frame_bgr.shape[:2]
    long_edge = max(h, w)
    if long_edge > max_edge and long_edge > 0:
        scale = max_edge / float(long_edge)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        frame_bgr = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise RuntimeError("cv2.imencode failed for cloud classifier frame")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _build_image_block(b64: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": b64,
        },
    }


def _extract_text(resp: Any) -> str:
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "") or ""
            if text:
                parts.append(text)
    return "".join(parts).strip()


@dataclass
class CloudHeavyClassifier:
    """Multi-frame theft/behavior classifier backed by Anthropic Claude.

    Drop-in replacement for the Qwen forward pass in
    ``VisionEngine._classify_with_qwen``. Takes a list of recent BGR
    frames + a prompt, returns the raw model text. Caller still runs
    the result through ``evaluate_classifier_output``.

    Construction is cheap — we only build the SDK client lazily on the
    first real call so importing the module on a CI worker without an
    API key never fails.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_HEAVY_MAX_TOKENS
    max_edge: int = DEFAULT_MAX_EDGE
    jpeg_quality: int = DEFAULT_JPEG_QUALITY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    api_key: str | None = None
    # Test seam — inject any object exposing ``.messages.create(...)``.
    client: Any | None = None

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.getenv("ANTHROPIC_API_KEY") or None

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed. `pip install anthropic` "
                "or set CLASSIFIER_BACKEND=qwen."
            ) from exc
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is empty. Cloud classifier needs an API key. "
                "Set ANTHROPIC_API_KEY in .env or switch to CLASSIFIER_BACKEND=qwen."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_seconds)
        return self.client

    def classify(self, frames_bgr: Sequence[np.ndarray], prompt: str) -> str:
        """Run the heavy VLM prompt with one or more frames. Raises on
        transport / SDK error so the engine's existing retry + log path
        in ``_classification_worker`` can do its thing."""
        if not frames_bgr:
            raise ValueError("frames_bgr must contain at least one frame")

        encoded = [
            _encode_jpeg_b64(
                f, max_edge=self.max_edge, jpeg_quality=self.jpeg_quality,
            )
            for f in frames_bgr
        ]
        content: list[dict[str, Any]] = [_build_image_block(b) for b in encoded]
        content.append({"type": "text", "text": prompt})

        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        text = _extract_text(resp)
        if not text:
            log.warning("cloud classifier returned empty text response")
        return text


@dataclass
class CloudClothingDescriber:
    """Cloud-backed describer compatible with ``QwenClothingCaptioner``.

    Same callable contract as ``_RealQwenDescriber``: ``(crop) -> str``.
    Used for the cross-cam clothing caption only — does not see the heavy
    classification prompt. The captioner's own per-track cache wraps this,
    so each track triggers exactly one cloud call.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_CAPTION_MAX_TOKENS
    max_edge: int = DEFAULT_MAX_EDGE
    jpeg_quality: int = DEFAULT_JPEG_QUALITY
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    prompt: str = ""
    api_key: str | None = None
    client: Any | None = None

    def __post_init__(self) -> None:
        if not self.prompt:
            from .qwen_captioner import CAPTION_PROMPT
            self.prompt = CAPTION_PROMPT
        if self.api_key is None:
            self.api_key = os.getenv("ANTHROPIC_API_KEY") or None

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed. `pip install anthropic` "
                "or set CLASSIFIER_BACKEND=qwen."
            ) from exc
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is empty. Cloud captioner needs an API key. "
                "Set ANTHROPIC_API_KEY in .env or switch to CLASSIFIER_BACKEND=qwen."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_seconds)
        return self.client

    def __call__(self, crop: np.ndarray) -> str:
        b64 = _encode_jpeg_b64(
            crop, max_edge=self.max_edge, jpeg_quality=self.jpeg_quality,
        )
        content: list[dict[str, Any]] = [
            _build_image_block(b64),
            {"type": "text", "text": self.prompt},
        ]
        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )
        return _extract_text(resp)


__all__ = [
    "CloudHeavyClassifier",
    "CloudClothingDescriber",
    "DEFAULT_MODEL",
    "DEFAULT_MAX_EDGE",
    "DEFAULT_JPEG_QUALITY",
    "DEFAULT_HEAVY_MAX_TOKENS",
    "DEFAULT_CAPTION_MAX_TOKENS",
]
