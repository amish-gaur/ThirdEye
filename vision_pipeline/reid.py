"""Person re-identification embeddings via OSNet (torchreid).

Produces a 512-d L2-normalized float32 vector per person crop. Used by the
cross-camera trace pipeline: same person across cameras → high cosine
similarity in this embedding space, regardless of viewpoint or lighting.

Defaults to OSNet-x0_25, ~2 MB, MPS-compatible on Apple Silicon.

Pipeline:
    BGR uint8 crop (HxWx3, OpenCV native)
        ├─ BGR → RGB
        ├─ PIL Image
        ├─ resize to (256, 128), normalize to ImageNet mean/std
        ├─ OSNet forward pass on chosen device
        └─ L2-normalize → 512-d float32 numpy

NOTE: torchreid's `FeatureExtractor` defaults to ImageNet-pretrained
weights when no `model_path` is given. For best cross-camera precision,
download Market-1501 / MSMT17 ReID weights and pass `model_path=`.
TODO before stage demo: ship a Make target / setup script that fetches
osnet_x0_25_msmt17 weights into ~/.cache/torch/checkpoints/.
"""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np

# torch / torchreid are heavy imports; surface them at module load so
# the engine fails fast if the env isn't set up rather than mid-frame.
import torch
from torchreid.reid.utils import FeatureExtractor

EMBEDDING_DIM = 512
DEFAULT_MODEL = "osnet_x0_25"


def _pick_device() -> str:
    """Auto-pick the best torch device available."""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _to_rgb_uint8(crop: np.ndarray) -> np.ndarray:
    """Normalize a crop to RGB uint8 HxWx3, ready for PIL.

    Accepts BGR HxWx3 (OpenCV native), grayscale HxW, or already-RGB
    HxWx3. Rejects anything else with a clear error.
    """
    if not isinstance(crop, np.ndarray):
        raise TypeError(f"crop must be a numpy.ndarray, got {type(crop).__name__}")
    if crop.dtype != np.uint8:
        # Be permissive: if it's float in [0, 1], scale; otherwise reject.
        if np.issubdtype(crop.dtype, np.floating) and crop.min() >= 0 and crop.max() <= 1.0:
            crop = (crop * 255.0).round().clip(0, 255).astype(np.uint8)
        else:
            raise ValueError(
                f"crop must be uint8 (or float in [0,1]); got dtype={crop.dtype}"
            )

    if crop.ndim == 2:
        # Grayscale → fake-RGB by stacking
        crop = np.stack([crop, crop, crop], axis=-1)
    elif crop.ndim == 3 and crop.shape[2] == 3:
        # Assume BGR (OpenCV); flip to RGB.
        crop = crop[:, :, ::-1]
    elif crop.ndim == 3 and crop.shape[2] == 4:
        # RGBA → drop alpha, swap B/R
        crop = crop[:, :, [2, 1, 0]]
    else:
        raise ValueError(
            f"crop must be HxW or HxWx3 (or HxWx4); got shape={crop.shape}"
        )

    # Force contiguous so PIL conversion inside torchreid is happy.
    return np.ascontiguousarray(crop)


class ReIDExtractor:
    """Wraps torchreid's FeatureExtractor with a numpy-first, L2-normalized API.

    Thread-safety: a single instance holds one `torch.nn.Module` and is NOT
    safe for concurrent calls across threads. Construct one per subprocess
    (which matches the repo's subprocess-per-camera architecture).

    Memory: model + activations ≈ 80-150 MB per instance on MPS.
    """

    embedding_dim: int = EMBEDDING_DIM

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        model_path: str | None = None,
        device: str | None = None,
        image_size: tuple[int, int] = (256, 128),
        verbose: bool = False,
    ) -> None:
        self.device = device or _pick_device()
        self.model_name = model_name

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._extractor = FeatureExtractor(
                model_name=model_name,
                model_path=model_path or "",
                device=self.device,
                image_size=image_size,
                verbose=verbose,
            )

    # ----- public API --------------------------------------------------

    def embed(self, crop: np.ndarray) -> np.ndarray:
        """Return a single L2-normalized 512-d float32 embedding."""
        rgb = _to_rgb_uint8(crop)
        feats = self._forward([rgb])  # (1, 512)
        return feats[0]

    def embed_batch(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        """Return (N, 512) L2-normalized float32 embeddings.

        Empty input returns an (0, 512) array (no GPU work)."""
        if len(crops) == 0:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        rgb_list = [_to_rgb_uint8(c) for c in crops]
        return self._forward(rgb_list)

    # ----- helpers -----------------------------------------------------

    def _forward(self, rgb_list: list[np.ndarray]) -> np.ndarray:
        """Run the model on a list of RGB uint8 crops; return (N, D) L2-normalized."""
        with torch.no_grad():
            feats = self._extractor(rgb_list)  # torch.Tensor (N, D) on self.device
        feats = feats.detach().to("cpu", dtype=torch.float32)
        # L2 normalize each row; guard against zero vectors.
        norms = feats.norm(dim=1, keepdim=True).clamp(min=1e-12)
        feats = feats / norms
        return feats.numpy().astype(np.float32, copy=False)

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity for L2-normalized vectors. Returns scalar in [-1, 1]."""
        return float(np.dot(a, b))


__all__ = ["ReIDExtractor", "EMBEDDING_DIM", "DEFAULT_MODEL"]
