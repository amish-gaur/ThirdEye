"""Qwen2-VL clothing captioner for the cross-camera search pipeline.

Bridges a person crop → free-form clothing description that
`vision_pipeline.tags.parse_caption` can convert into a filterable
tag dict.

Design choices:
- **Lazy load.** The 2B model is ~5GB on MPS. We don't load weights
  until the first caption call so test imports stay cheap and the
  ingestion script can choose whether to pay the cost.
- **Cache by track id.** A track is one person; one Qwen call per
  track is enough. Subsequent samples on the same track reuse the
  cached caption.
- **Errors degrade silently.** If Qwen OOMs or fails, we return ""
  rather than raise — the search demo can still operate on tracks
  that did get a caption.
- **Light prompt.** We do not reuse the heavy theft-classification
  JSON prompt from `events.py`; for cross-cam search we only need a
  short clothing/accessory description. Cheaper, fewer hallucinations.

Real model wiring lives in `_RealQwenDescriber` and is constructed
only when no `_describe` callable is injected.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("vision_pipeline.qwen_captioner")

DEFAULT_MODEL = "Qwen/Qwen2-VL-2B-Instruct"

CAPTION_PROMPT = (
    "Describe this person's clothing and accessories in 8-15 words. "
    "Include color, garment type (hoodie, jacket, shirt, pants, etc.), "
    "and any visible accessories (backpack, hat, bag). "
    "Do NOT include numbers or IDs. "
    "Example: 'tall man in red hoodie and dark jeans with a backpack'."
)

DescribeFn = Callable[[np.ndarray], str]


def _truncate_words(text: str, n: int) -> str:
    words = text.split()
    return " ".join(words[:n])


@dataclass
class QwenClothingCaptioner:
    """Callable: (track_id, crop_bgr) -> caption string.

    Pass a custom `_describe` for unit tests. Default lazily loads the
    Qwen2-VL-2B-Instruct weights on first call.
    """

    model_name: str = DEFAULT_MODEL
    device: str | None = None
    max_words: int = 18

    _describe: Optional[DescribeFn] = None
    _cache: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        # Don't load the model here — lazy load on first call.
        pass

    def __call__(self, track_id: int, crop: np.ndarray) -> str:
        with self._lock:
            cached = self._cache.get(track_id)
            if cached is not None:
                return cached

        try:
            descriptor = self._get_describer()
            raw = descriptor(crop) or ""
        except Exception as exc:
            log.warning("Qwen captioner failed for track %d: %s", track_id, exc)
            raw = ""

        text = _truncate_words(raw.strip(), self.max_words)
        with self._lock:
            self._cache[track_id] = text
        return text

    # --- describer plumbing --------------------------------------------

    def _get_describer(self) -> DescribeFn:
        if self._describe is None:
            self._describe = _RealQwenDescriber(
                model_name=self.model_name, device=self.device,
            )
        return self._describe


# ----------------------------------------------------------------------
# Real Qwen2-VL describer (loaded lazily)
# ----------------------------------------------------------------------


class _RealQwenDescriber:  # pragma: no cover - exercises real GPU/model
    """Tiny wrapper around Qwen2-VL-2B-Instruct for one short caption.

    Excluded from coverage: this class is intentionally untested in CI
    because it would download multi-GB weights and require MPS/CUDA.
    The unit tests inject a fake `_describe` callable instead.
    """

    def __init__(self, model_name: str, device: str | None) -> None:
        import torch
        from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device

        log.info("loading Qwen captioner model=%s device=%s", model_name, device)
        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name, torch_dtype=torch.float16,
        ).to(device).eval()

    def __call__(self, crop: np.ndarray) -> str:
        from PIL import Image
        import cv2
        import torch

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": CAPTION_PROMPT},
                ],
            },
        ]
        prompt_text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        inputs = self._processor(
            text=[prompt_text],
            images=[pil_image],
            padding=True,
            return_tensors="pt",
        ).to(self.device)
        with torch.no_grad():
            out = self._model.generate(
                **inputs,
                max_new_tokens=60,
                do_sample=False,
            )
        generated = out[:, inputs["input_ids"].shape[1]:]
        text = self._processor.batch_decode(
            generated, skip_special_tokens=True,
        )[0]
        return text.strip()


__all__ = [
    "QwenClothingCaptioner",
    "CAPTION_PROMPT",
    "DEFAULT_MODEL",
]
