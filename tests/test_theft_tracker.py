from types import SimpleNamespace

from vision_pipeline.theft_tracker import (
    PackageDetection,
    PackageTheftTracker,
    STATE_PACKAGE_ANCHORED,
    STATE_THEFT_CONFIRMED,
)


def _cfg(**overrides):
    base = dict(
        anchor_seconds=0.3,
        move_px=30.0,
        move_iou=0.35,
        package_missing_grace_seconds=0.4,
        person_near_package_window_seconds=2.0,
        interaction_window_seconds=2.0,
        feet_motion_enable=True,
        feet_motion_min_area=1500.0,
        theft_cooldown_seconds=5.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _pkg(box=(100.0, 200.0, 180.0, 280.0), conf=0.8, label="backpack"):
    return PackageDetection(label=label, confidence=conf, box=box)


def _person(box=(90.0, 120.0, 220.0, 420.0)):
    return box


def test_stationary_package_person_then_removed_emits_theft() -> None:
    t = PackageTheftTracker(_cfg())
    for i in range(5):
        d = t.update(
            now=1000.0 + i * 0.1,
            person_boxes=[],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )
    assert d.state == STATE_PACKAGE_ANCHORED

    t.update(
        now=1000.5,
        person_boxes=[_person()],
        package_dets=[_pkg()],
        feet_motion_present=False,
    )
    out = t.update(
        now=1001.0,
        person_boxes=[_person()],
        package_dets=[],
        feet_motion_present=False,
    )
    assert out.should_emit is True
    assert out.state == STATE_THEFT_CONFIRMED


def test_person_passby_without_package_move_does_not_emit() -> None:
    t = PackageTheftTracker(_cfg())
    for i in range(5):
        t.update(
            now=1000.0 + i * 0.1,
            person_boxes=[],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )

    emits = []
    for i in range(12):
        out = t.update(
            now=1000.5 + i * 0.1,
            person_boxes=[_person()],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )
        emits.append(out.should_emit)
    assert not any(emits)


def test_package_disappears_without_person_does_not_emit() -> None:
    t = PackageTheftTracker(_cfg())
    for i in range(5):
        t.update(
            now=1000.0 + i * 0.1,
            person_boxes=[],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )
    out = t.update(
        now=1001.0,
        person_boxes=[],
        package_dets=[],
        feet_motion_present=False,
    )
    assert out.should_emit is False


def test_feet_motion_then_package_removed_emits_theft() -> None:
    t = PackageTheftTracker(_cfg())
    for i in range(5):
        t.update(
            now=1000.0 + i * 0.1,
            person_boxes=[],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )
    t.update(
        now=1000.5,
        person_boxes=[],
        package_dets=[_pkg()],
        feet_motion_present=True,
    )
    out = t.update(
        now=1001.0,
        person_boxes=[],
        package_dets=[],
        feet_motion_present=True,
    )
    assert out.should_emit is True


def test_theft_emits_once_for_single_incident() -> None:
    t = PackageTheftTracker(_cfg())
    for i in range(5):
        t.update(
            now=1000.0 + i * 0.1,
            person_boxes=[],
            package_dets=[_pkg()],
            feet_motion_present=False,
        )
    t.update(
        now=1000.5,
        person_boxes=[_person()],
        package_dets=[_pkg()],
        feet_motion_present=False,
    )
    first = t.update(
        now=1001.0,
        person_boxes=[_person()],
        package_dets=[],
        feet_motion_present=False,
    )
    second = t.update(
        now=1001.3,
        person_boxes=[_person()],
        package_dets=[],
        feet_motion_present=False,
    )
    assert first.should_emit is True
    assert second.should_emit is False
