"""ReID extractor tests.

These tests verify the contract of `vision_pipeline.reid.ReIDExtractor`:
shape, dtype, determinism, L2-normalization, and basic discriminative
behavior on synthetic inputs.

Cross-camera ReID quality (the demo-critical assertion) lives in
`test_reid_cross_cam.py` and runs only when fixture crops are present.
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchreid")

from vision_pipeline.reid import ReIDExtractor


@pytest.fixture(scope="module")
def extractor() -> ReIDExtractor:
    return ReIDExtractor(model_name="osnet_x0_25")


def _fake_crop(seed: int, h: int = 256, w: int = 128) -> np.ndarray:
    """Reproducible BGR uint8 crop. Different seeds produce different images."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def test_embed_shape_and_dtype(extractor: ReIDExtractor) -> None:
    crop = _fake_crop(seed=1)
    vec = extractor.embed(crop)
    assert vec.shape == (extractor.embedding_dim,)
    assert vec.dtype == np.float32


def test_embed_is_l2_normalized(extractor: ReIDExtractor) -> None:
    crop = _fake_crop(seed=2)
    vec = extractor.embed(crop)
    assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-5)


def test_embed_is_deterministic(extractor: ReIDExtractor) -> None:
    crop = _fake_crop(seed=3)
    v1 = extractor.embed(crop)
    v2 = extractor.embed(crop)
    # Same input must produce identical output (model is in eval mode, no dropout)
    assert np.allclose(v1, v2, atol=1e-5)


def test_embed_different_inputs_differ(extractor: ReIDExtractor) -> None:
    v1 = extractor.embed(_fake_crop(seed=10))
    v2 = extractor.embed(_fake_crop(seed=20))
    cos = float(np.dot(v1, v2))
    # Random noise crops should not be identical embeddings.
    assert cos < 0.999, f"random noise crops produced suspiciously similar embeddings (cos={cos:.4f})"


def test_embed_batch_matches_single(extractor: ReIDExtractor) -> None:
    crops = [_fake_crop(seed=s) for s in (4, 5, 6)]
    batched = extractor.embed_batch(crops)
    assert batched.shape == (3, extractor.embedding_dim)
    assert batched.dtype == np.float32
    # Each row is L2-normalized
    norms = np.linalg.norm(batched, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    # Batched results match single-call results
    for i, crop in enumerate(crops):
        single = extractor.embed(crop)
        assert np.allclose(batched[i], single, atol=1e-4)


def test_empty_batch_returns_empty(extractor: ReIDExtractor) -> None:
    out = extractor.embed_batch([])
    assert out.shape == (0, extractor.embedding_dim)
    assert out.dtype == np.float32


def test_invalid_input_raises(extractor: ReIDExtractor) -> None:
    with pytest.raises((TypeError, ValueError)):
        extractor.embed(np.zeros((10,), dtype=np.uint8))  # 1-D, not an image


def test_grayscale_input_handled(extractor: ReIDExtractor) -> None:
    """Grayscale (H, W) crops should either error cleanly or be auto-converted."""
    gray = np.random.randint(0, 256, size=(256, 128), dtype=np.uint8)
    try:
        vec = extractor.embed(gray)
        assert vec.shape == (extractor.embedding_dim,)
    except (TypeError, ValueError):
        pass  # explicit rejection is also acceptable


def test_cosine_helper(extractor: ReIDExtractor) -> None:
    """`cosine` should mirror `np.dot` for L2-normalized vectors."""
    a = extractor.embed(_fake_crop(seed=100))
    b = extractor.embed(_fake_crop(seed=101))
    cos_helper = ReIDExtractor.cosine(a, b)
    cos_dot = float(np.dot(a, b))
    assert np.isclose(cos_helper, cos_dot, atol=1e-5)
    assert -1.0 <= cos_helper <= 1.0
