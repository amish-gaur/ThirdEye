from unittest.mock import Mock

from vision_pipeline.config import Config
from vision_pipeline.publisher import PublishResult, post_event
from vision_pipeline.engine import VisionEngine


def test_post_event_uses_router_url(mocker) -> None:
    response = Mock(status_code=200, ok=True, text='{"ok":true}')
    post = mocker.patch("vision_pipeline.publisher.requests.post", return_value=response)

    cfg = Config(
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
        qwen_frame_lookback_seconds=1.2,
        classification_cooldown_seconds=8.0,
        action_router_url="https://router.test/event",
        person_confidence=0.35,
        post_timeout_seconds=4.0,
        post_events=True,
        show_window=False,
        mock_classifier=False,
    )
    event = {"event_id": "evt_123", "tier": 3}
    result = post_event(event, cfg)

    assert result.ok is True
    assert result.status_code == 200
    post.assert_called_once_with(
        "https://router.test/event",
        json=event,
        timeout=4.0,
    )


def test_publish_logs_clear_error_for_offline_ngrok_endpoint(mocker) -> None:
    mocker.patch("vision_pipeline.engine.require_mps", return_value="mps")
    mocker.patch("vision_pipeline.engine.YOLO")
    cfg = Config(
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
        qwen_frame_lookback_seconds=1.2,
        classification_cooldown_seconds=8.0,
        action_router_url="https://example.ngrok-free.dev/event",
        person_confidence=0.35,
        carryable_confidence=0.25,
        post_timeout_seconds=4.0,
        post_events=True,
        show_window=False,
        mock_classifier=True,
    )

    engine = VisionEngine(cfg, source=0, show_window=False)
    log = mocker.patch("vision_pipeline.engine.log")

    engine._log_router_delivery_issue(
        PublishResult(
            status_code=404,
            ok=False,
            body="The endpoint example.ngrok-free.dev is offline. (ERR_NGROK_3200)",
        )
    )

    assert log.error.called
