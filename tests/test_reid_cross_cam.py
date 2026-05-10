"""Cross-camera ReID quality test (the day-1 blocking test).

Asserts the demo-critical invariant: same person across two different
cameras has higher embedding similarity than two different people on
the same or different cameras.

This test is fixture-gated. It runs only when crop fixtures are
present at tests/fixtures/reid/. To populate:

    .venv/bin/python scripts/build_reid_fixtures.py \\
        --video data/demo/cam_1.mp4 --cam-id 1 --person-label A \\
        --time 12.5 --bbox 220,80,360,420
    .venv/bin/python scripts/build_reid_fixtures.py \\
        --video data/demo/cam_2.mp4 --cam-id 2 --person-label A \\
        --time 28.1 --bbox 540,140,690,520
    .venv/bin/python scripts/build_reid_fixtures.py \\
        --video data/demo/cam_1.mp4 --cam-id 1 --person-label B \\
        --time 44.0 --bbox 100,90,230,400

Need at minimum: person_A on cams 1+2 AND person_B on cam 1.

NOTE: With ImageNet-pretrained weights (the torchreid default) the
discriminative gap is smaller than with Market-1501/MSMT17 weights.
The test asserts RELATIVE ordering — same-person similarity must
beat different-people similarity — rather than absolute thresholds.
This is exactly the property the demo needs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("torchreid")
cv2 = pytest.importorskip("cv2")

from vision_pipeline.reid import ReIDExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reid"


def _load_bgr(path: Path) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        pytest.fail(f"could not load fixture {path}")
    return img


def _have(*names: str) -> bool:
    return all((FIXTURE_DIR / n).exists() for n in names)


@pytest.fixture(scope="module")
def extractor() -> ReIDExtractor:
    return ReIDExtractor()


@pytest.mark.skipif(
    not _have("person_A_cam1.jpg", "person_A_cam2.jpg", "person_B_cam1.jpg"),
    reason=(
        "ReID cross-cam fixtures missing. Run "
        "scripts/build_reid_fixtures.py to populate "
        "tests/fixtures/reid/. See test docstring."
    ),
)
def test_same_person_across_cams_beats_different_people(
    extractor: ReIDExtractor,
) -> None:
    a_cam1 = extractor.embed(_load_bgr(FIXTURE_DIR / "person_A_cam1.jpg"))
    a_cam2 = extractor.embed(_load_bgr(FIXTURE_DIR / "person_A_cam2.jpg"))
    b_cam1 = extractor.embed(_load_bgr(FIXTURE_DIR / "person_B_cam1.jpg"))

    same_person = ReIDExtractor.cosine(a_cam1, a_cam2)
    diff_person_same_cam = ReIDExtractor.cosine(a_cam1, b_cam1)
    diff_person_cross_cam = ReIDExtractor.cosine(a_cam2, b_cam1)

    # The whole demo lives or dies on this ordering. Same-person
    # cross-camera similarity must beat different-people similarity.
    margin = same_person - max(diff_person_same_cam, diff_person_cross_cam)
    assert margin > 0.05, (
        f"ReID does not separate same-vs-different person reliably:\n"
        f"  same person  (A_cam1, A_cam2)   = {same_person:.4f}\n"
        f"  diff people  (A_cam1, B_cam1)   = {diff_person_same_cam:.4f}\n"
        f"  diff people  (A_cam2, B_cam1)   = {diff_person_cross_cam:.4f}\n"
        f"  margin                           = {margin:.4f} (need > 0.05)\n"
        f"If you see this, swap to MSMT17/Market-1501 ReID-trained "
        f"weights (see vision_pipeline/reid.py docstring)."
    )


@pytest.mark.skipif(
    not _have("person_A_cam1.jpg", "person_A_cam2.jpg"),
    reason="Need at minimum person_A on two cams.",
)
def test_same_person_cross_cam_above_baseline(
    extractor: ReIDExtractor,
) -> None:
    """Sanity floor: cross-cam similarity for the same person must beat 0.20."""
    a_cam1 = extractor.embed(_load_bgr(FIXTURE_DIR / "person_A_cam1.jpg"))
    a_cam2 = extractor.embed(_load_bgr(FIXTURE_DIR / "person_A_cam2.jpg"))
    sim = ReIDExtractor.cosine(a_cam1, a_cam2)
    assert sim > 0.20, (
        f"Same-person cross-cam similarity = {sim:.4f} is below the 0.20 "
        f"floor. Either fixtures are mislabeled, or the model weights "
        f"are not loading. Check that the crops actually depict the "
        f"same person."
    )
