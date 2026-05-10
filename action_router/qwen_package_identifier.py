"""Package/order identification using Qwen visual matching.

Public entry point:
    identify_package(clip_path, event) -> PackageMatch

The router owns the return shape, but the caller owns the order source. Pass
candidate orders in the event payload under one of:
    orders, candidate_orders, expected_packages, packages, recent_orders

Each candidate may be a dict with order_id/id and title/order_title/name, or a
plain string. As a fallback, set PACKAGE_ORDERS_PATH to a JSON file containing
a list of orders or {"orders": [...]}.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import CONFIG

log = logging.getLogger("action_router.package_identifier")

ORDER_LIST_KEYS = (
    "orders",
    "candidate_orders",
    "expected_packages",
    "packages",
    "recent_orders",
)
ORDER_ID_KEYS = ("order_id", "id", "orderId", "orderID", "package_order_id")
ORDER_TITLE_KEYS = (
    "order_title",
    "title",
    "name",
    "item",
    "description",
    "product_name",
)


@dataclass(frozen=True)
class PackageCandidate:
    order_id: str
    title: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "title": self.title,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PackageMatch:
    order_id: str | None
    order_title: str | None
    confidence: float
    candidates: list[PackageCandidate] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_title": self.order_title,
            "confidence": self.confidence,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class _Order:
    order_id: str
    title: str


def identify_package(clip_path: str, event: dict[str, Any]) -> PackageMatch:
    """Identify which known order appears in a theft/delivery clip.

    Returns:
        PackageMatch matching the requested shape:
        {order_id, order_title, confidence, candidates, reasoning}
    """
    orders = _load_orders(event)
    if not orders:
        return PackageMatch(
            order_id=None,
            order_title=None,
            confidence=0.0,
            candidates=[],
            reasoning="No candidate orders were provided in the event or PACKAGE_ORDERS_PATH.",
        )

    explicit = _explicit_order_match(event, orders)
    if explicit:
        return explicit

    try:
        raw = _call_qwen_for_package_match(clip_path, event, orders)
        if raw:
            return _match_from_qwen(raw, orders)
    except Exception as exc:
        log.warning("Qwen package identification failed; using heuristic fallback: %s", exc)

    return _heuristic_match(event, orders)


def _load_orders(event: dict[str, Any]) -> list[_Order]:
    orders: list[_Order] = []
    for key in ORDER_LIST_KEYS:
        orders.extend(_coerce_orders(event.get(key)))

    single_order = event.get("order")
    if single_order:
        orders.extend(_coerce_orders([single_order]))

    if not orders:
        path = str(
            event.get("orders_path")
            or getattr(CONFIG, "package_orders_path", "")
            or os.getenv("PACKAGE_ORDERS_PATH", "")
        ).strip()
        if path:
            orders.extend(_load_orders_file(Path(path)))

    deduped: dict[str, _Order] = {}
    for order in orders:
        deduped.setdefault(order.order_id, order)
    return list(deduped.values())


def _coerce_orders(value: Any) -> list[_Order]:
    if not value:
        return []
    if isinstance(value, dict):
        if isinstance(value.get("orders"), list):
            return _coerce_orders(value["orders"])
        value = [value]
    if not isinstance(value, list):
        return []

    orders: list[_Order] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            text = item.strip()
            if text:
                orders.append(_Order(order_id=text, title=text))
            continue
        if not isinstance(item, dict):
            continue
        order_id = _first_text(item, ORDER_ID_KEYS) or f"candidate_{index}"
        title = _first_text(item, ORDER_TITLE_KEYS) or order_id
        orders.append(_Order(order_id=order_id, title=title))
    return orders


def _load_orders_file(path: Path) -> list[_Order]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read package order file %s: %s", path, exc)
        return []
    if isinstance(payload, dict):
        for key in ORDER_LIST_KEYS:
            if key in payload:
                return _coerce_orders(payload[key])
    return _coerce_orders(payload)


def _first_text(mapping: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _explicit_order_match(event: dict[str, Any], orders: list[_Order]) -> PackageMatch | None:
    explicit_id = _first_text(
        event,
        (
            "order_id",
            "matched_order_id",
            "package_order_id",
            "suspected_order_id",
        ),
    )
    if not explicit_id:
        return None
    by_id = {order.order_id: order for order in orders}
    order = by_id.get(explicit_id)
    if not order:
        return None
    return PackageMatch(
        order_id=order.order_id,
        order_title=order.title,
        confidence=1.0,
        candidates=[PackageCandidate(order.order_id, order.title, 1.0)],
        reasoning="Event already included an explicit order id.",
    )


def _call_qwen_for_package_match(
    clip_path: str, event: dict[str, Any], orders: list[_Order]
) -> str:
    frames = _sample_clip_frames(Path(clip_path))
    if not frames:
        raise ValueError(f"no readable frames in clip: {clip_path}")

    processor, model, device = _load_qwen()
    prompt = _build_qwen_prompt(event, orders)
    images = [_frame_to_pil(frame) for frame in frames]
    content: list[dict[str, Any]] = [{"type": "image"} for _ in images]
    content.append({"type": "text", "text": prompt})
    messages = [{"role": "user", "content": content}]
    prompt_text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = processor(
        text=[prompt_text],
        images=images,
        padding=True,
        return_tensors="pt",
    )
    inputs = {
        key: value.to(device) if hasattr(value, "to") else value
        for key, value in inputs.items()
    }

    import torch

    max_new_tokens = int(getattr(CONFIG, "package_identifier_qwen_max_new_tokens", 160))
    with torch.inference_mode():
        generated_ids = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=max_new_tokens,
        )
    prompt_length = inputs["input_ids"].shape[1]
    generated_ids = generated_ids[:, prompt_length:]
    return processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()


@lru_cache(maxsize=1)
def _load_qwen() -> tuple[Any, Any, str]:
    import torch
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration

    model_name = str(
        getattr(CONFIG, "package_identifier_qwen_model", "")
        or os.getenv("PACKAGE_IDENTIFIER_QWEN_MODEL", "")
        or os.getenv("QWEN_MODEL", "Qwen/Qwen2-VL-2B-Instruct")
    )
    if torch.backends.mps.is_available():
        device = "mps"
        dtype = torch.float16
    elif torch.cuda.is_available():
        device = "cuda"
        dtype = torch.float16
    else:
        device = "cpu"
        dtype = torch.float32

    processor = AutoProcessor.from_pretrained(
        model_name,
        min_pixels=int(getattr(CONFIG, "package_identifier_qwen_min_pixels", 256 * 28 * 28)),
        max_pixels=int(getattr(CONFIG, "package_identifier_qwen_max_pixels", 512 * 28 * 28)),
    )
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        model_name,
        torch_dtype=dtype,
    ).to(device)
    model.eval()
    return processor, model, device


def _build_qwen_prompt(event: dict[str, Any], orders: list[_Order]) -> str:
    order_rows = [
        {"order_id": order.order_id, "title": order.title}
        for order in orders
    ]
    event_context = {
        "one_line_summary": event.get("one_line_summary"),
        "suspect_description": event.get("suspect_description"),
        "scene": event.get("scene"),
        "behavior_pattern": event.get("behavior_pattern"),
        "time_elapsed": event.get("time_elapsed"),
    }
    return (
        "You are SafeWatch's package/order identifier. You will be shown recent "
        "frames from a delivery/theft clip and a list of possible orders. Match "
        "the visible package to the most likely order using visible cues such as "
        "box/bag size, shape, labels, brand text, color, and any event context. "
        "If the package cannot be distinguished, use null and low confidence.\n\n"
        "Candidate orders JSON:\n"
        f"{json.dumps(order_rows, ensure_ascii=True)}\n\n"
        "Event context JSON:\n"
        f"{json.dumps(event_context, ensure_ascii=True)}\n\n"
        "Return JSON only, no markdown, exactly this shape:\n"
        "{\n"
        '  "order_id": "<matching order_id or null>",\n'
        '  "order_title": "<matching title or null>",\n'
        '  "confidence": 0.0,\n'
        '  "candidates": [{"order_id": "<id>", "title": "<title>", "confidence": 0.0}],\n'
        '  "reasoning": "<short visual reason>"\n'
        "}\n"
        "Only use order_id values from Candidate orders JSON."
    )


def _sample_clip_frames(path: Path) -> list[Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        from PIL import Image

        return [_downscale_pil(Image.open(path).convert("RGB"))]

    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    max_frames = max(1, int(getattr(CONFIG, "package_identifier_qwen_frames", 3)))
    if frame_count > 1:
        positions = [
            int(round(i * (frame_count - 1) / max(1, max_frames - 1)))
            for i in range(max_frames)
        ]
    else:
        positions = [0]

    frames: list[Any] = []
    for pos in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(_downscale_cv2_frame(frame))
    cap.release()
    return frames


def _downscale_cv2_frame(frame: Any) -> Any:
    import cv2

    max_edge = max(64, int(getattr(CONFIG, "package_identifier_qwen_frame_max_edge", 512)))
    height, width = frame.shape[:2]
    edge = max(height, width)
    if edge <= max_edge:
        return frame
    scale = max_edge / float(edge)
    return cv2.resize(frame, (int(width * scale), int(height * scale)))


def _downscale_pil(image: Any) -> Any:
    max_edge = max(64, int(getattr(CONFIG, "package_identifier_qwen_frame_max_edge", 512)))
    width, height = image.size
    edge = max(width, height)
    if edge <= max_edge:
        return image
    scale = max_edge / float(edge)
    return image.resize((int(width * scale), int(height * scale)))


def _frame_to_pil(frame: Any) -> Any:
    from PIL import Image

    if isinstance(frame, Image.Image):
        return frame.convert("RGB")
    import cv2

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame_rgb)


def _match_from_qwen(raw_text: str, orders: list[_Order]) -> PackageMatch:
    payload = _parse_json_object(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("Qwen did not return a JSON object")
    known = {order.order_id: order for order in orders}
    candidates = _normalize_candidates(payload.get("candidates"), known)

    order_id = _nullable_text(payload.get("order_id"))
    if order_id not in known:
        order_id = candidates[0].order_id if candidates else None

    order = known.get(order_id or "")
    confidence = _clamp_confidence(payload.get("confidence"))
    if order and candidates:
        candidate_conf = next(
            (
                candidate.confidence
                for candidate in candidates
                if candidate.order_id == order.order_id
            ),
            None,
        )
        if candidate_conf is not None:
            confidence = max(confidence, candidate_conf)

    return PackageMatch(
        order_id=order.order_id if order else None,
        order_title=order.title if order else None,
        confidence=confidence if order else 0.0,
        candidates=candidates,
        reasoning=_nullable_text(payload.get("reasoning")) or "Qwen visual match.",
    )


def _normalize_candidates(value: Any, known: dict[str, _Order]) -> list[PackageCandidate]:
    if not isinstance(value, list):
        return []
    candidates: list[PackageCandidate] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        order_id = _nullable_text(item.get("order_id"))
        order = known.get(order_id or "")
        if not order:
            continue
        candidates.append(
            PackageCandidate(
                order_id=order.order_id,
                title=order.title,
                confidence=_clamp_confidence(item.get("confidence")),
            )
        )
    candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return candidates


def _parse_json_object(raw_text: str) -> Any:
    text = raw_text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)


def _heuristic_match(event: dict[str, Any], orders: list[_Order]) -> PackageMatch:
    context = " ".join(
        str(event.get(key) or "")
        for key in (
            "package_description",
            "one_line_summary",
            "suspect_description",
            "scene",
            "raw_classifier",
        )
    )
    context_tokens = _tokens(context)
    scored: list[PackageCandidate] = []
    for order in orders:
        title_tokens = _tokens(order.title)
        if not title_tokens:
            overlap = 0.0
        else:
            overlap = len(context_tokens & title_tokens) / len(title_tokens)
        if len(orders) == 1 and overlap == 0.0:
            confidence = 0.35
        else:
            confidence = min(0.75, overlap)
        scored.append(PackageCandidate(order.order_id, order.title, confidence))
    scored.sort(key=lambda candidate: candidate.confidence, reverse=True)
    best = scored[0] if scored and scored[0].confidence > 0 else None
    return PackageMatch(
        order_id=best.order_id if best else None,
        order_title=best.title if best else None,
        confidence=best.confidence if best else 0.0,
        candidates=scored[:5],
        reasoning="Qwen was unavailable; used event text overlap as a fallback.",
    )


def _tokens(text: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "of", "to", "from", "with", "in", "on"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stop}


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return text


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
