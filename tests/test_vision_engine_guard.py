from vision_pipeline.config import Config
from vision_pipeline.engine import (
    BOX_CLASS_IDS,
    BehaviorTracker,
    CandidateContext,
    ClassificationRequest,
    Detection,
    PERSON_CLASS_ID,
    STATE_CANDIDATE,
    STATE_IDLE,
    STATE_SUPPRESSED,
    STATE_WATCHING,
    VisionEngine,
)


# ── Helpers ──────────────────────────────────────────────────────────────

FRAME_SIZE = (640, 480)
ZONE = (0.0, 0.0, 1.0, 1.0)  # entire frame = zone for easy testing


def _cfg(**overrides):
    """Build a Config with sensible test defaults.  All new fields included."""
    base = dict(
        node_id="node_local",
        camera_source="0",
        capture_width=640,
        capture_height=480,
        yolo_model="yolo11n.pt",
        yolo_input_size=640,
        qwen_model="Qwen/Qwen2-VL-2B-Instruct",
        qwen_max_new_tokens=96,
        qwen_min_pixels=256 * 28 * 28,
        qwen_max_pixels=512 * 28 * 28,
        qwen_frame_max_edge=512,
        classification_cooldown_seconds=8.0,
        action_router_url="http://127.0.0.1:8001/event",
        person_confidence=0.45,
        carryable_confidence=0.25,
        post_timeout_seconds=10.0,
        post_events=False,
        show_window=False,
        mock_classifier=False,
        debug_overlay=False,
        debug_detections=False,
        save_failure_artifacts=False,
        debug_artifact_dir="./debug_vision_test",
        entry_zone=ZONE,
        carryable_labels=("backpack", "handbag", "suitcase"),
        interaction_frames_required=4,
        min_dwell_seconds=0.3,
        carryable_grace_seconds=0.6,
        person_exit_seconds=1.5,
        scene_clear_seconds=3.5,
        pair_iou_threshold=0.0,
        pair_distance_ratio=1.5,
        demo_mode_theft_bias=False,
    )
    base.update(overrides)
    return Config(**base)


def _person(conf=0.65, x1=100.0, y1=50.0, x2=250.0, y2=400.0):
    return Detection(cls_id=0, label="person", confidence=conf,
                     box=(x1, y1, x2, y2))


def _backpack(conf=0.40, x1=120.0, y1=200.0, x2=220.0, y2=350.0):
    return Detection(cls_id=24, label="backpack", confidence=conf,
                     box=(x1, y1, x2, y2))


def _handbag(conf=0.35, x1=130.0, y1=210.0, x2=200.0, y2=340.0):
    return Detection(cls_id=26, label="handbag", confidence=conf,
                     box=(x1, y1, x2, y2))


def _suitcase(conf=0.38, x1=110.0, y1=190.0, x2=230.0, y2=370.0):
    return Detection(cls_id=28, label="suitcase", confidence=conf,
                     box=(x1, y1, x2, y2))


def _feed_interaction(tracker, *, frames, start_time=1000.0, dt=0.1):
    """Feed N frames of person+backpack inside zone. Return list of decisions."""
    decisions = []
    for i in range(frames):
        t = start_time + i * dt
        dec = tracker.update(
            now=t,
            person_dets=[_person()],
            carryable_dets=[_backpack()],
            frame_size=FRAME_SIZE,
        )
        decisions.append(dec)
    return decisions


# ── Original VisionEngine tests (updated for new config) ────────────────


def test_qwen_and_yolo_are_moved_to_mps(mocker) -> None:
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    yolo_cls = mocker.patch("vision_pipeline.engine.YOLO")
    processor_cls = mocker.patch("vision_pipeline.engine.AutoProcessor.from_pretrained")
    model_cls = mocker.patch(
        "vision_pipeline.engine.Qwen2VLForConditionalGeneration.from_pretrained"
    )
    qwen_model = model_cls.return_value
    qwen_model.to.return_value = qwen_model

    VisionEngine(_cfg(), source=0, show_window=False)

    yolo_cls.return_value.to.assert_called_once_with("mps")
    processor_cls.assert_called_once_with(
        "Qwen/Qwen2-VL-2B-Instruct",
        min_pixels=256 * 28 * 28,
        max_pixels=512 * 28 * 28,
    )
    model_cls.assert_called_once_with(
        "Qwen/Qwen2-VL-2B-Instruct",
        torch_dtype=__import__("torch").float16,
    )
    qwen_model.to.assert_called_once_with("mps")
    qwen_model.eval.assert_called_once_with()


def test_submit_classification_marks_in_flight(mocker) -> None:
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    mocker.patch("vision_pipeline.engine.YOLO")
    mocker.patch("vision_pipeline.engine.AutoProcessor.from_pretrained")
    mocker.patch("vision_pipeline.engine.threading.Thread.start")
    model_cls = mocker.patch(
        "vision_pipeline.engine.Qwen2VLForConditionalGeneration.from_pretrained"
    )
    model = model_cls.return_value
    model.to.return_value = model

    engine = VisionEngine(_cfg(), source=0, show_window=False)
    request = ClassificationRequest(
        timestamp=1.0,
        frame_seq=2,
        frame_bgr="frame",
        yolo_classes=["person"],
    )

    submitted = engine._submit_classification(request)

    assert submitted is True
    assert engine._classification_busy() is True


def test_detected_classes_requests_person_and_carryable_objects(mocker) -> None:
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    yolo_cls = mocker.patch("vision_pipeline.engine.YOLO")

    engine = VisionEngine(_cfg(mock_classifier=True), source=0, show_window=False)
    yolo_result = mocker.Mock()
    yolo_result.names = {0: "person", 24: "backpack", 26: "handbag", 28: "suitcase"}
    yolo_result.boxes = mocker.Mock()
    yolo_result.boxes.__len__ = mocker.Mock(return_value=2)
    yolo_result.boxes.cls.tolist.return_value = [0, 24]
    yolo_cls.return_value.predict.return_value = [yolo_result]

    detected = engine._detected_classes("frame")

    assert detected == ["backpack", "person"]
    yolo_cls.return_value.predict.assert_called_once()
    assert yolo_cls.return_value.predict.call_args.kwargs["classes"] == [
        PERSON_CLASS_ID,
        *BOX_CLASS_IDS,
    ]


def test_mock_classifier_skips_model_load(mocker) -> None:
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    mocker.patch("vision_pipeline.engine.YOLO")
    processor_from_pretrained = mocker.patch(
        "vision_pipeline.engine.AutoProcessor.from_pretrained"
    )
    model_from_pretrained = mocker.patch(
        "vision_pipeline.engine.Qwen2VLForConditionalGeneration.from_pretrained"
    )

    engine = VisionEngine(
        _cfg(mock_classifier=True),
        source=0,
        show_window=False,
    )

    assert engine.processor is None
    assert engine.qwen is None
    processor_from_pretrained.assert_not_called()
    model_from_pretrained.assert_not_called()


# ── NEW: Separate threshold behavior ────────────────────────────────────


def test_separate_thresholds_person_filtered_carryable_kept(mocker) -> None:
    """Person at 0.30 < person_confidence (0.45) is filtered out.
    Backpack at 0.30 >= carryable_confidence (0.25) is kept."""
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    yolo_cls = mocker.patch("vision_pipeline.engine.YOLO")

    engine = VisionEngine(
        _cfg(mock_classifier=True, person_confidence=0.45, carryable_confidence=0.25),
        source=0,
        show_window=False,
    )

    yolo_result = mocker.Mock()
    yolo_result.names = {0: "person", 24: "backpack"}
    yolo_result.boxes = mocker.Mock()
    yolo_result.boxes.__len__ = mocker.Mock(return_value=2)
    yolo_result.boxes.cls.tolist.return_value = [0, 24]
    yolo_result.boxes.conf.tolist.return_value = [0.30, 0.30]
    yolo_result.boxes.xyxy.tolist.return_value = [
        [100.0, 50.0, 250.0, 400.0],
        [120.0, 200.0, 220.0, 350.0],
    ]
    yolo_cls.return_value.predict.return_value = [yolo_result]

    persons, carryables = engine._detect_persons_and_carryables("frame")

    assert len(persons) == 0, "person at 0.30 should be below person_confidence=0.45"
    assert len(carryables) == 1, "backpack at 0.30 should pass carryable_confidence=0.25"
    assert carryables[0].label == "backpack"


def test_separate_thresholds_both_kept_when_above(mocker) -> None:
    """Both person and backpack kept when above their respective thresholds."""
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    yolo_cls = mocker.patch("vision_pipeline.engine.YOLO")

    engine = VisionEngine(
        _cfg(mock_classifier=True, person_confidence=0.45, carryable_confidence=0.25),
        source=0,
        show_window=False,
    )

    yolo_result = mocker.Mock()
    yolo_result.names = {0: "person", 24: "backpack"}
    yolo_result.boxes = mocker.Mock()
    yolo_result.boxes.__len__ = mocker.Mock(return_value=2)
    yolo_result.boxes.cls.tolist.return_value = [0, 24]
    yolo_result.boxes.conf.tolist.return_value = [0.65, 0.40]
    yolo_result.boxes.xyxy.tolist.return_value = [
        [100.0, 50.0, 250.0, 400.0],
        [120.0, 200.0, 220.0, 350.0],
    ]
    yolo_cls.return_value.predict.return_value = [yolo_result]

    persons, carryables = engine._detect_persons_and_carryables("frame")

    assert len(persons) == 1
    assert len(carryables) == 1
    assert persons[0].confidence == 0.65
    assert carryables[0].confidence == 0.40


# ── NEW: Carryable grace window ─────────────────────────────────────────


def test_carryable_grace_window_survives_dropped_frame() -> None:
    """When a bag disappears for one frame (within grace window), the cue
    still reports carryable_recent and the candidate does not collapse."""
    cfg = _cfg(
        interaction_frames_required=3,
        min_dwell_seconds=0.1,
        carryable_grace_seconds=0.6,
    )
    tracker = BehaviorTracker(cfg)

    # Frame 1-2: person + backpack present
    _feed_interaction(tracker, frames=2, start_time=1000.0, dt=0.1)

    # Frame 3: backpack disappears (person still present)
    dec = tracker.update(
        now=1000.2,
        person_dets=[_person()],
        carryable_dets=[],  # dropped frame
        frame_size=FRAME_SIZE,
    )

    assert tracker.candidate is not None, "candidate must survive a single dropped frame"
    has_recent_cue = any("carryable_recent" in c for c in dec.cues)
    assert has_recent_cue, f"expected carryable_recent cue, got {dec.cues}"


def test_carryable_grace_window_expires() -> None:
    """After grace window expires, carryable is no longer considered active."""
    cfg = _cfg(carryable_grace_seconds=0.3)
    tracker = BehaviorTracker(cfg)

    # Frame 1: person + backpack
    tracker.update(
        now=1000.0,
        person_dets=[_person()],
        carryable_dets=[_backpack()],
        frame_size=FRAME_SIZE,
    )

    # Jump well beyond grace window
    dec = tracker.update(
        now=1001.0,
        person_dets=[_person()],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )

    has_carryable_cue = any("carryable" in c for c in dec.cues)
    assert not has_carryable_cue, f"carryable should have expired, got {dec.cues}"


# ── NEW: Stable candidate across dropped frame ──────────────────────────


def test_candidate_stable_across_single_dropped_detection() -> None:
    """Candidate interaction_frames should keep accumulating even when
    one frame misses the bag, as long as the grace window covers it."""
    cfg = _cfg(
        interaction_frames_required=6,
        min_dwell_seconds=0.1,
        carryable_grace_seconds=0.6,
    )
    tracker = BehaviorTracker(cfg)

    # 3 good frames
    _feed_interaction(tracker, frames=3, start_time=1000.0, dt=0.1)
    assert tracker.candidate is not None
    frames_before_drop = tracker.candidate.interaction_frames

    # 1 dropped bag frame (person still present, bag within grace)
    tracker.update(
        now=1000.3,
        person_dets=[_person()],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )

    # Candidate should still exist and the pair should still match via grace
    assert tracker.candidate is not None
    # interaction_frames should have incremented (bag was within grace, pair still holds)
    assert tracker.candidate.interaction_frames >= frames_before_drop

    # 2 more good frames: candidate keeps building
    for i in range(2):
        tracker.update(
            now=1000.4 + i * 0.1,
            person_dets=[_person()],
            carryable_dets=[_backpack()],
            frame_size=FRAME_SIZE,
        )

    assert tracker.candidate.interaction_frames >= frames_before_drop + 2


# ── NEW: Scene-clear resets candidate and suppression ────────────────────


def test_scene_clear_resets_after_timeout() -> None:
    """After scene_clear_seconds of no signal, suppression drops and
    candidate is cleared, allowing a fresh alert."""
    cfg = _cfg(
        interaction_frames_required=2,
        min_dwell_seconds=0.05,
        scene_clear_seconds=2.0,
        classification_cooldown_seconds=0.0,
    )
    tracker = BehaviorTracker(cfg)

    # Build up and fire candidate
    decs = _feed_interaction(tracker, frames=4, start_time=1000.0, dt=0.1)
    fired = [d for d in decs if d.should_classify]
    assert len(fired) >= 1, "should have fired at least once"
    assert tracker.suppression_active

    # No detections for scene_clear_seconds
    dec = tracker.update(
        now=1003.0,
        person_dets=[],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )

    assert not tracker.suppression_active, "suppression should clear after scene_clear timeout"
    assert tracker.candidate is None, "candidate should be reset after scene clear"
    assert dec.state == STATE_IDLE


def test_scene_clear_allows_realert() -> None:
    """After scene clears, a new interaction cycle can fire a second alert."""
    cfg = _cfg(
        interaction_frames_required=2,
        min_dwell_seconds=0.05,
        scene_clear_seconds=1.0,
        classification_cooldown_seconds=0.0,
    )
    tracker = BehaviorTracker(cfg)

    # First interaction -> fires
    decs1 = _feed_interaction(tracker, frames=4, start_time=1000.0, dt=0.1)
    fires1 = [d for d in decs1 if d.should_classify]
    assert len(fires1) >= 1

    # Clear scene
    tracker.update(now=1002.0, person_dets=[], carryable_dets=[], frame_size=FRAME_SIZE)

    # Second interaction -> should fire again
    decs2 = _feed_interaction(tracker, frames=4, start_time=1003.0, dt=0.1)
    fires2 = [d for d in decs2 if d.should_classify]
    assert len(fires2) >= 1, "second interaction after scene-clear should produce a new alert"


# ── NEW: One alert per continuous interaction ────────────────────────────


def test_single_alert_for_continuous_interaction() -> None:
    """One continuous person+bag interaction should produce exactly one
    should_classify=True, not repeated alerts every few frames."""
    cfg = _cfg(
        interaction_frames_required=3,
        min_dwell_seconds=0.1,
        scene_clear_seconds=5.0,
        classification_cooldown_seconds=8.0,
    )
    tracker = BehaviorTracker(cfg)

    # 20 continuous frames of person + backpack
    decs = _feed_interaction(tracker, frames=20, start_time=1000.0, dt=0.1)
    fires = [d for d in decs if d.should_classify]
    assert len(fires) == 1, f"expected exactly 1 alert, got {len(fires)}"

    # After firing, suppression is active
    assert tracker.suppression_active


# ── NEW: BehaviorTracker state transitions ───────────────────────────────


def test_idle_to_watching_on_partial_signal() -> None:
    """Person in zone without carryable -> WATCHING, not CANDIDATE."""
    tracker = BehaviorTracker(_cfg())
    dec = tracker.update(
        now=1000.0,
        person_dets=[_person()],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )
    assert dec.state == STATE_WATCHING
    assert "person_in_zone" in dec.cues


def test_idle_when_nothing_detected() -> None:
    tracker = BehaviorTracker(_cfg())
    dec = tracker.update(
        now=1000.0,
        person_dets=[],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )
    assert dec.state == STATE_IDLE
    assert dec.cues == []


def test_candidate_state_on_paired_interaction() -> None:
    """Person + backpack in zone -> CANDIDATE after enough frames."""
    cfg = _cfg(interaction_frames_required=2, min_dwell_seconds=0.05)
    tracker = BehaviorTracker(cfg)
    decs = _feed_interaction(tracker, frames=3, start_time=1000.0, dt=0.1)
    # At least one frame should be in CANDIDATE state
    candidate_states = [d for d in decs if d.state == STATE_CANDIDATE]
    assert len(candidate_states) >= 1


def test_suppressed_state_after_alert_fires() -> None:
    cfg = _cfg(
        interaction_frames_required=2,
        min_dwell_seconds=0.05,
        classification_cooldown_seconds=0.0,
    )
    tracker = BehaviorTracker(cfg)
    decs = _feed_interaction(tracker, frames=4, start_time=1000.0, dt=0.1)

    # Find the frame where alert fires
    fired_idx = None
    for i, d in enumerate(decs):
        if d.should_classify:
            fired_idx = i
            break
    assert fired_idx is not None

    # All subsequent frames in this interaction should be SUPPRESSED
    for d in decs[fired_idx + 1:]:
        assert d.state == STATE_SUPPRESSED


# ── NEW: Carryable label logging ────────────────────────────────────────


def test_carryable_label_logged_in_cues() -> None:
    """When a bag is detected, the cue includes which label fired."""
    tracker = BehaviorTracker(_cfg())
    dec = tracker.update(
        now=1000.0,
        person_dets=[_person()],
        carryable_dets=[_handbag()],
        frame_size=FRAME_SIZE,
    )
    carryable_cues = [c for c in dec.cues if "handbag" in c]
    assert len(carryable_cues) >= 1, f"expected handbag in cues, got {dec.cues}"


def test_carryable_label_in_candidate_context() -> None:
    """CandidateContext remembers the carryable label that triggered it."""
    cfg = _cfg(interaction_frames_required=2, min_dwell_seconds=0.05)
    tracker = BehaviorTracker(cfg)

    tracker.update(
        now=1000.0,
        person_dets=[_person()],
        carryable_dets=[_suitcase()],
        frame_size=FRAME_SIZE,
    )
    tracker.update(
        now=1000.1,
        person_dets=[_person()],
        carryable_dets=[_suitcase()],
        frame_size=FRAME_SIZE,
    )

    assert tracker.candidate is not None
    assert tracker.candidate.last_carryable_label == "suitcase"


# ── NEW: Demo mode tuning ───────────────────────────────────────────────


def test_demo_mode_fires_faster() -> None:
    """Demo mode reduces interaction_frames_required and min_dwell, so
    alert fires sooner than normal mode."""
    normal_cfg = _cfg(
        interaction_frames_required=6,
        min_dwell_seconds=0.5,
        classification_cooldown_seconds=0.0,
        demo_mode_theft_bias=False,
    )
    demo_cfg = _cfg(
        interaction_frames_required=6,
        min_dwell_seconds=0.5,
        classification_cooldown_seconds=0.0,
        demo_mode_theft_bias=True,
    )

    normal_tracker = BehaviorTracker(normal_cfg)
    demo_tracker = BehaviorTracker(demo_cfg)

    # Feed 5 frames
    normal_decs = _feed_interaction(normal_tracker, frames=5, start_time=1000.0, dt=0.15)
    demo_decs = _feed_interaction(demo_tracker, frames=5, start_time=1000.0, dt=0.15)

    normal_fires = sum(1 for d in normal_decs if d.should_classify)
    demo_fires = sum(1 for d in demo_decs if d.should_classify)

    # Demo should fire within 5 frames (reduced requirement = max(2, 6-2) = 4)
    # Normal needs 6 frames and 0.5s dwell, unlikely in 5 frames at 0.15 dt (0.6s ok but 5 < 6 frames)
    assert demo_fires >= 1, "demo mode should fire within 5 frames"
    assert normal_fires == 0, "normal mode should NOT fire within 5 frames (needs 6)"


def test_demo_mode_extends_carryable_grace() -> None:
    """Demo mode doubles carryable_grace_seconds."""
    demo_cfg = _cfg(carryable_grace_seconds=0.5, demo_mode_theft_bias=True)
    tracker = BehaviorTracker(demo_cfg)

    assert tracker.carryable_grace_seconds == 1.0  # 0.5 * 2.0

    normal_cfg = _cfg(carryable_grace_seconds=0.5, demo_mode_theft_bias=False)
    normal_tracker = BehaviorTracker(normal_cfg)
    assert normal_tracker.carryable_grace_seconds == 0.5


def test_demo_mode_stronger_suppression_via_longer_scene_clear() -> None:
    """Demo mode uses 1.5x scene_clear_seconds for stickier suppression."""
    demo_cfg = _cfg(scene_clear_seconds=2.0, demo_mode_theft_bias=True)
    tracker = BehaviorTracker(demo_cfg)
    assert tracker.scene_clear_seconds == 3.0  # 2.0 * 1.5

    normal_cfg = _cfg(scene_clear_seconds=2.0, demo_mode_theft_bias=False)
    normal_tracker = BehaviorTracker(normal_cfg)
    assert normal_tracker.scene_clear_seconds == 2.0


# ── NEW: CandidateContext richness ───────────────────────────────────────


def test_candidate_tracks_first_and_last_seen() -> None:
    cfg = _cfg(interaction_frames_required=10, min_dwell_seconds=0.1)
    tracker = BehaviorTracker(cfg)
    _feed_interaction(tracker, frames=5, start_time=1000.0, dt=0.1)

    cand = tracker.candidate
    assert cand is not None
    assert cand.first_seen_at == 1000.0
    assert cand.last_seen_at >= 1000.4
    assert cand.interaction_frames == 5
    assert cand.recent_zone_dwell > 0


def test_candidate_remembers_scene_signature() -> None:
    cfg = _cfg(interaction_frames_required=10, min_dwell_seconds=0.1)
    tracker = BehaviorTracker(cfg)
    _feed_interaction(tracker, frames=3, start_time=1000.0, dt=0.1)

    assert tracker.candidate is not None
    assert tracker.candidate.last_scene_signature is not None
    assert "backpack" in tracker.candidate.last_scene_signature


def test_candidate_not_cleared_on_single_cue_disappearing() -> None:
    """Candidate persists if person stays even though bag vanishes briefly."""
    cfg = _cfg(
        interaction_frames_required=10,
        min_dwell_seconds=0.1,
        carryable_grace_seconds=0.5,
        scene_clear_seconds=3.0,
    )
    tracker = BehaviorTracker(cfg)
    _feed_interaction(tracker, frames=4, start_time=1000.0, dt=0.1)
    assert tracker.candidate is not None

    # Bag disappears, person stays — within grace window
    tracker.update(
        now=1000.4,
        person_dets=[_person()],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )
    assert tracker.candidate is not None, "candidate must not disappear when only one cue drops"

    # Person disappears too but within scene_clear timeout
    tracker.update(
        now=1000.5,
        person_dets=[],
        carryable_dets=[],
        frame_size=FRAME_SIZE,
    )
    # Candidate should still exist (scene not cleared yet)
    assert tracker.candidate is not None


# ── NEW: Near-miss detection ─────────────────────────────────────────────


def test_near_miss_flagged_on_partial_evidence() -> None:
    """When evidence is meaningful but not enough, near_miss is set."""
    cfg = _cfg(
        interaction_frames_required=6,
        min_dwell_seconds=0.2,
        classification_cooldown_seconds=0.0,
    )
    tracker = BehaviorTracker(cfg)
    # Feed 4 frames = 4 >= max(2, 6//2) = 3, and dwell ~0.3s >= 0.2*0.5=0.1
    decs = _feed_interaction(tracker, frames=4, start_time=1000.0, dt=0.1)

    near_misses = [d for d in decs if d.near_miss]
    assert len(near_misses) >= 1, "should flag near_miss for partial evidence"
    # But no actual fire
    fires = [d for d in decs if d.should_classify]
    assert len(fires) == 0
