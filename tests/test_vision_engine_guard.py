from vision_pipeline.config import Config
from vision_pipeline.engine import (
    BOX_CLASS_IDS,
    ClassificationRequest,
    PERSON_CLASS_ID,
    VisionEngine,
)


def _cfg(**overrides):
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
        person_confidence=0.35,
        post_timeout_seconds=10.0,
        post_events=False,
        show_window=False,
        mock_classifier=False,
    )
    base.update(overrides)
    return Config(**base)


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
