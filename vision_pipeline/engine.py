"""YOLO + Qwen2-VL vision engine that emits router-compatible events."""

from __future__ import annotations

import argparse
import json
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from ultralytics import YOLO

from .config import CONFIG, Config
from .events import VISION_LANGUAGE_PROMPT, build_event, parse_classifier_output
from .publisher import post_event

FRAME_BUFFER_MAXLEN = 150
TARGET_FPS = 10
FRAME_INTERVAL_SECONDS = 1.0 / TARGET_FPS
PERSON_CLASS_ID = 0
CONSECUTIVE_PERSON_FRAMES = 2

log = logging.getLogger("vision_pipeline.engine")


@dataclass
class BufferedFrame:
    timestamp: float
    frame_bgr: Any


@dataclass
class ClassificationRequest:
    timestamp: float
    frame_seq: int
    frame_bgr: Any
    yolo_classes: list[str]


def require_mps() -> str:
    if not torch.backends.mps.is_available():
        raise RuntimeError(
            "MPS is not available. This script is intended for Apple Silicon "
            "with a PyTorch build that supports `.to('mps')`."
        )
    return "mps"


def frame_to_pil(frame_bgr: Any) -> Image.Image:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


def parse_capture_source(raw_source: str) -> int | str:
    raw_source = raw_source.strip()
    if raw_source.isdigit():
        return int(raw_source)
    return raw_source


class VisionEngine:
    def __init__(self, config: Config, source: int | str, show_window: bool) -> None:
        self.config = config
        self.device = require_mps()
        self.source = source
        self.show_window = show_window
        self.frame_buffer: deque[BufferedFrame] = deque(maxlen=FRAME_BUFFER_MAXLEN)
        self.person_streak = 0
        self.frame_seq = 0
        self.last_classification_at = 0.0
        self.classification_queue: queue.Queue[ClassificationRequest | None] = queue.Queue(
            maxsize=1
        )
        self.classification_in_flight = False
        self.state_lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None

        self.yolo = YOLO(config.yolo_model)
        self.yolo.to(self.device)

        self.processor = None
        self.qwen = None
        if not self.config.mock_classifier:
            self.processor = AutoProcessor.from_pretrained(
                config.qwen_model,
                min_pixels=config.qwen_min_pixels,
                max_pixels=config.qwen_max_pixels,
            )
            self.qwen = Qwen2VLForConditionalGeneration.from_pretrained(
                config.qwen_model,
                torch_dtype=torch.float16,
            )
            self.qwen = self.qwen.to(self.device)
            self.qwen.eval()
            self.worker_thread = threading.Thread(
                target=self._classification_worker,
                name="qwen-classifier",
                daemon=True,
            )
            self.worker_thread.start()
        log.info(
            "Vision engine ready device=%s source=%r yolo=%s qwen=%s capture=%sx%s qwen_pixels=%s-%s cooldown=%ss post_events=%s router_url=%s mock_classifier=%s",
            self.device,
            self.source,
            self.config.yolo_model,
            self.config.qwen_model,
            self.config.capture_width,
            self.config.capture_height,
            self.config.qwen_min_pixels,
            self.config.qwen_max_pixels,
            self.config.classification_cooldown_seconds,
            self.config.post_events,
            self.config.action_router_url,
            self.config.mock_classifier,
        )

    def run(self) -> None:
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            raise RuntimeError(
                f"Unable to open camera source {self.source!r}. "
                "Check that the webcam or RTSP stream is accessible."
            )

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.capture_height)

        if self.show_window:
            print("Vision engine running. Press 'q' in the preview window to quit.")
        else:
            print("Vision engine running without a preview window. Use Ctrl+C to quit.")

        try:
            while True:
                loop_started_at = time.time()

                ok, frame = cap.read()
                if not ok:
                    log.warning("Webcam / stream frame grab failed; retrying.")
                    self._throttle_loop(loop_started_at)
                    continue

                self.frame_seq += 1
                captured_at = time.time()
                self.frame_buffer.append(
                    BufferedFrame(timestamp=captured_at, frame_bgr=frame.copy())
                )

                if self._classification_busy():
                    detected_classes = []
                    self.person_streak = 0
                else:
                    detected_classes = self._detected_classes(frame)
                    person_detected = "person" in detected_classes
                    self.person_streak = self.person_streak + 1 if person_detected else 0

                if (
                    self.person_streak >= CONSECUTIVE_PERSON_FRAMES
                    and self._classification_due(captured_at)
                ):
                    latest_frame = self.frame_buffer[-1]
                    request = ClassificationRequest(
                        timestamp=latest_frame.timestamp,
                        frame_seq=self.frame_seq,
                        frame_bgr=latest_frame.frame_bgr.copy(),
                        yolo_classes=detected_classes or ["person"],
                    )
                    if self._submit_classification(request):
                        self.last_classification_at = captured_at
                    self.person_streak = 0

                if self.show_window:
                    cv2.imshow("SafeWatch Vision Engine", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break

                self._throttle_loop(loop_started_at)
        finally:
            cap.release()
            if self.show_window:
                cv2.destroyAllWindows()
            self._stop_worker()

    def _detected_classes(self, frame_bgr: Any) -> list[str]:
        results = self.yolo.predict(
            source=frame_bgr,
            classes=[PERSON_CLASS_ID],
            conf=self.config.person_confidence,
            device=self.device,
            imgsz=self.config.yolo_input_size,
            verbose=False,
        )
        if not results:
            return []

        names = results[0].names
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []

        detected_ids = {int(cls_id) for cls_id in boxes.cls.tolist()}
        return sorted(str(names[idx]) for idx in detected_ids)

    def _classify_with_qwen(
        self, frame_bgr: Any, time_elapsed_seconds: float
    ) -> tuple[dict[str, Any] | None, str]:
        if self.config.mock_classifier:
            raw_answer = json.dumps(
                {
                    "tier": 3,
                    "confidence": 0.9,
                    "suspect_description": "person detected by mock classifier",
                    "one_line_summary": "person detected near the camera",
                    "time_elapsed": "ignored",
                }
            )
            parsed = parse_classifier_output(raw_answer, time_elapsed_seconds)
            return parsed, raw_answer

        image = frame_to_pil(self._downscale_frame_for_qwen(frame_bgr))
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": VISION_LANGUAGE_PROMPT},
                ],
            }
        ]
        prompt_text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.processor(
            text=[prompt_text],
            images=[image],
            padding=True,
            return_tensors="pt",
        )
        inputs = self._move_inputs_to_device(inputs)

        with torch.inference_mode():
            generated_ids = self.qwen.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=self.config.qwen_max_new_tokens,
            )

        prompt_length = inputs["input_ids"].shape[1]
        generated_ids = generated_ids[:, prompt_length:]
        raw_answer = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        self._empty_mps_cache()
        parsed = parse_classifier_output(raw_answer, time_elapsed_seconds)
        if parsed is None:
            log.warning("Qwen returned invalid classifier output: %r", raw_answer)
        return parsed, raw_answer

    def _submit_classification(self, request: ClassificationRequest) -> bool:
        if self.config.mock_classifier:
            return False
        with self.state_lock:
            if self.classification_in_flight:
                return False
            self.classification_in_flight = True
        try:
            self.classification_queue.put_nowait(request)
            return True
        except queue.Full:
            with self.state_lock:
                self.classification_in_flight = False
            return False

    def _classification_worker(self) -> None:
        while True:
            request = self.classification_queue.get()
            if request is None:
                self.classification_queue.task_done()
                return

            try:
                classification_started_at = time.time()
                parsed, raw_answer = self._classify_with_qwen(
                    request.frame_bgr,
                    classification_started_at - request.timestamp,
                )
                if parsed is None:
                    continue

                event = build_event(
                    classification=parsed,
                    node_id=self.config.node_id,
                    frame_seq=request.frame_seq,
                    yolo_classes=request.yolo_classes,
                    raw_classifier=raw_answer,
                    timestamp=request.timestamp,
                )
                print(json.dumps(event, ensure_ascii=True))
                self._publish_event(event)
            except Exception:
                log.exception("Background Qwen classification failed.")
            finally:
                with self.state_lock:
                    self.classification_in_flight = False
                self.classification_queue.task_done()

    def _stop_worker(self) -> None:
        if self.worker_thread is None:
            return
        try:
            self.classification_queue.put_nowait(None)
        except queue.Full:
            pass
        self.worker_thread.join(timeout=1.0)

    def _classification_busy(self) -> bool:
        with self.state_lock:
            return self.classification_in_flight

    def _classification_due(self, now: float) -> bool:
        return (now - self.last_classification_at) >= self.config.classification_cooldown_seconds

    def _downscale_frame_for_qwen(self, frame_bgr: Any) -> Any:
        max_edge = self.config.qwen_frame_max_edge
        height, width = frame_bgr.shape[:2]
        largest_edge = max(height, width)
        if largest_edge <= max_edge:
            return frame_bgr

        scale = max_edge / float(largest_edge)
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        return cv2.resize(frame_bgr, (new_width, new_height), interpolation=cv2.INTER_AREA)

    def _move_inputs_to_device(self, inputs: Any) -> dict[str, Any]:
        moved: dict[str, Any] = {}
        for key, value in inputs.items():
            moved[key] = value.to(self.device) if isinstance(value, torch.Tensor) else value
        return moved

    @staticmethod
    def _empty_mps_cache() -> None:
        mps = getattr(torch, "mps", None)
        if mps is None or not hasattr(mps, "empty_cache"):
            return
        try:
            mps.empty_cache()
        except RuntimeError:
            pass

    def _publish_event(self, event: dict[str, Any]) -> None:
        if not self.config.post_events:
            return
        try:
            result = post_event(event, self.config)
        except Exception as exc:
            log.warning("Action router POST failed: %s", exc)
            return

        if result.ok:
            log.info(
                "Posted event %s to router (%s)",
                event["event_id"],
                result.status_code,
            )
            return

        log.warning(
            "Action router returned %s for event %s: %s",
            result.status_code,
            event["event_id"],
            result.body,
        )

    @staticmethod
    def _throttle_loop(loop_started_at: float) -> None:
        elapsed = time.time() - loop_started_at
        remaining = FRAME_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            time.sleep(remaining)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SafeWatch vision pipeline with YOLO11n and Qwen2-VL."
    )
    parser.add_argument(
        "--source",
        default=CONFIG.camera_source,
        help="Camera source. Use 0 for the local webcam or an RTSP URL.",
    )
    parser.add_argument(
        "--hide-window",
        action="store_true",
        help="Disable the OpenCV preview window.",
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        help="Print the event JSON but do not POST it to the action router.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    config = CONFIG
    if args.no_post:
        config = Config(
            node_id=CONFIG.node_id,
            camera_source=CONFIG.camera_source,
            capture_width=CONFIG.capture_width,
            capture_height=CONFIG.capture_height,
            yolo_model=CONFIG.yolo_model,
            yolo_input_size=CONFIG.yolo_input_size,
            qwen_model=CONFIG.qwen_model,
            qwen_max_new_tokens=CONFIG.qwen_max_new_tokens,
            qwen_min_pixels=CONFIG.qwen_min_pixels,
            qwen_max_pixels=CONFIG.qwen_max_pixels,
            qwen_frame_max_edge=CONFIG.qwen_frame_max_edge,
            classification_cooldown_seconds=CONFIG.classification_cooldown_seconds,
            action_router_url=CONFIG.action_router_url,
            person_confidence=CONFIG.person_confidence,
            post_timeout_seconds=CONFIG.post_timeout_seconds,
            post_events=False,
            show_window=CONFIG.show_window,
            mock_classifier=CONFIG.mock_classifier,
        )

    engine = VisionEngine(
        config=config,
        source=parse_capture_source(args.source),
        show_window=False if args.hide_window else config.show_window,
    )
    engine.run()
