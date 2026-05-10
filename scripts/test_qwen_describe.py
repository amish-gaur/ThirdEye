"""Diagnostic: capture ONE frame from the webcam (or load an image) and run
Qwen on it, printing both the raw answer and the post-scrubber payload.

Use this to sanity-check what Qwen actually says about you BEFORE running the
full pipeline. If Qwen invents clothing colors or leaks "person 0.08", you'll
see it here and can decide whether to retune the prompt or accept the result.

Examples:
    python -m scripts.test_qwen_describe                # snap webcam, describe
    python -m scripts.test_qwen_describe --image foo.jpg # describe an image
    python -m scripts.test_qwen_describe --camera 1     # second camera
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from vision_pipeline.config import CONFIG
from vision_pipeline.events import (
    VISION_LANGUAGE_PROMPT,
    evaluate_classifier_output,
)


def _capture_frame_from_webcam(camera_index: int):
    import cv2  # local import so script still works for --image without a camera

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera index {camera_index}")
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG.capture_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG.capture_height)
    # Discard a few warmup frames so exposure settles.
    for _ in range(5):
        cap.read()
        time.sleep(0.05)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise SystemExit("Camera returned no frame")
    return frame


def _load_image(path: Path):
    import cv2

    frame = cv2.imread(str(path))
    if frame is None:
        raise SystemExit(f"Could not load image at {path}")
    return frame


def _run_qwen(frames_bgr) -> str:
    """Run Qwen on a single frame OR a list of frames (multi-image)."""
    import cv2  # noqa: F401
    import torch
    from PIL import Image
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

    if not isinstance(frames_bgr, list):
        frames_bgr = [frames_bgr]

    if not torch.backends.mps.is_available():
        print("WARNING: MPS not available, falling back to CPU (slow).", file=sys.stderr)
        device = "cpu"
    else:
        device = "mps"

    processor = AutoProcessor.from_pretrained(
        CONFIG.qwen_model,
        min_pixels=CONFIG.qwen_min_pixels,
        max_pixels=CONFIG.qwen_max_pixels,
    )
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        CONFIG.qwen_model,
        torch_dtype=torch.float16,
    ).to(device)
    model.eval()

    images = []
    for frame_bgr in frames_bgr:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        images.append(Image.fromarray(frame_rgb))

    content = [{"type": "image"} for _ in images]
    content.append({"type": "text", "text": VISION_LANGUAGE_PROMPT})
    messages = [{"role": "user", "content": content}]
    prompt_text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(
        text=[prompt_text], images=images, padding=True, return_tensors="pt"
    )
    inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}

    with torch.inference_mode():
        ids = model.generate(
            **inputs, do_sample=False, max_new_tokens=CONFIG.qwen_max_new_tokens
        )
    prompt_length = inputs["input_ids"].shape[1]
    ids = ids[:, prompt_length:]
    return processor.batch_decode(
        ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
    )[0].strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="Describe a still image instead of webcam")
    parser.add_argument("--camera", type=int, default=int(CONFIG.camera_source) if CONFIG.camera_source.isdigit() else 0)
    parser.add_argument("--save", type=Path, default=None, help="Save the captured frame to this path")
    parser.add_argument("--repeat", type=int, default=1, help="Run N times (different frames) to check consistency")
    parser.add_argument(
        "--frames",
        type=int,
        default=CONFIG.qwen_frames_per_inference,
        help="How many recent frames to send Qwen as multi-image (1-4). Default from CONFIG.",
    )
    args = parser.parse_args()

    print("Loading Qwen2-VL... (first run downloads ~5GB of weights)")
    print()

    for i in range(args.repeat):
        if args.image:
            frame = _load_image(args.image)
            frames = [frame]
            label = f"image={args.image.name}"
        else:
            frames = []
            for f_idx in range(max(1, args.frames)):
                frames.append(_capture_frame_from_webcam(args.camera))
                if f_idx < args.frames - 1:
                    time.sleep(0.4)
            frame = frames[-1]
            label = f"webcam-frames {len(frames)}  attempt {i + 1}/{args.repeat}"

        if args.save:
            import cv2

            target = args.save if args.repeat == 1 else args.save.with_stem(args.save.stem + f"_{i + 1}")
            cv2.imwrite(str(target), frame)
            print(f"Saved last frame to {target}")

        raw = _run_qwen(frames)
        result = evaluate_classifier_output(raw, 0.0)

        print("=" * 70)
        print(f"[{label}]  status={result.status}  reason={result.reason}")
        print("--- RAW QWEN OUTPUT ---")
        print(raw)
        print("--- AFTER VALIDATOR (this is what the router sees) ---")
        print(json.dumps(result.payload, indent=2) if result.payload else "(none)")
        print()
        if i < args.repeat - 1:
            time.sleep(0.4)


if __name__ == "__main__":
    main()
