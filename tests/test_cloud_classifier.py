"""Cloud-Claude VLM backend tests.

We never reach the real Anthropic API in unit tests. Instead we inject
a fake client that matches the SDK's ``client.messages.create(...)``
shape and asserts on the request payload. This keeps the tests fast,
offline, and deterministic, while still catching regressions in image
encoding, prompt wiring, and the multi-frame content block layout.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from vision_pipeline.cloud_classifier import (
    CloudClothingDescriber,
    CloudHeavyClassifier,
    _encode_jpeg_b64,
)


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeResponse:
    content: list[_FakeTextBlock]


class _FakeMessages:
    def __init__(self, scripted_text: str) -> None:
        self.scripted_text = scripted_text
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(content=[_FakeTextBlock(text=self.scripted_text)])


class _FakeAnthropicClient:
    def __init__(self, scripted_text: str) -> None:
        self.messages = _FakeMessages(scripted_text)


def _bgr_frame(seed: int = 0, w: int = 320, h: int = 240) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# _encode_jpeg_b64
# ---------------------------------------------------------------------------


def test_encode_jpeg_b64_returns_decodable_jpeg() -> None:
    frame = _bgr_frame()
    b64 = _encode_jpeg_b64(frame, max_edge=512, jpeg_quality=80)
    raw = base64.b64decode(b64)
    # JPEG SOI marker.
    assert raw[:2] == b"\xff\xd8"


def test_encode_jpeg_b64_downscales_long_edge() -> None:
    import cv2

    big = _bgr_frame(w=2000, h=1000)
    b64 = _encode_jpeg_b64(big, max_edge=400, jpeg_quality=70)
    raw = base64.b64decode(b64)
    decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    h, w = decoded.shape[:2]
    assert max(h, w) <= 400


def test_encode_jpeg_b64_rejects_empty() -> None:
    with pytest.raises(ValueError):
        _encode_jpeg_b64(np.zeros((0, 0, 3), dtype=np.uint8))


# ---------------------------------------------------------------------------
# CloudHeavyClassifier
# ---------------------------------------------------------------------------


_SCRIPTED_JSON = json.dumps(
    {
        "tier": 3,
        "behavior_pattern": "taking_item",
        "confidence": 0.78,
        "scene": "front porch",
        "suspect_description": "tall man in red hoodie with a backpack",
        "one_line_summary": "person grabbed package off porch and walked away",
        "time_elapsed": "ignored",
    }
)


def test_heavy_classifier_builds_multi_image_payload() -> None:
    fake = _FakeAnthropicClient(_SCRIPTED_JSON)
    clf = CloudHeavyClassifier(client=fake, model="claude-haiku-4-5", max_tokens=300)

    raw = clf.classify(
        [_bgr_frame(1), _bgr_frame(2), _bgr_frame(3)],
        prompt="HEAVY PROMPT",
    )

    assert raw == _SCRIPTED_JSON
    assert len(fake.messages.calls) == 1
    call = fake.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["max_tokens"] == 300
    content = call["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "image", "text"]
    assert content[-1]["text"] == "HEAVY PROMPT"
    for block in content[:-1]:
        src = block["source"]
        assert src["type"] == "base64"
        assert src["media_type"] == "image/jpeg"
        assert isinstance(src["data"], str) and src["data"]


def test_heavy_classifier_extracts_text_only() -> None:
    @dataclass
    class _NonText:
        type: str = "tool_use"

    @dataclass
    class _Text:
        text: str
        type: str = "text"

    class _Msgs:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return type(
                "R",
                (),
                {"content": [_NonText(), _Text(text="from claude")]},
            )()

    class _Client:
        def __init__(self) -> None:
            self.messages = _Msgs()

    clf = CloudHeavyClassifier(client=_Client())
    out = clf.classify([_bgr_frame()], prompt="P")
    assert out == "from claude"


def test_heavy_classifier_requires_at_least_one_frame() -> None:
    clf = CloudHeavyClassifier(client=_FakeAnthropicClient(_SCRIPTED_JSON))
    with pytest.raises(ValueError):
        clf.classify([], prompt="P")


def test_heavy_classifier_raises_without_api_key_or_client(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clf = CloudHeavyClassifier(api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        clf.classify([_bgr_frame()], prompt="P")


def test_heavy_classifier_passthrough_lets_parser_validate() -> None:
    """The cloud backend returns raw text — we don't pre-parse here.
    The engine pipes it into evaluate_classifier_output unchanged."""
    from vision_pipeline.events import evaluate_classifier_output

    fake = _FakeAnthropicClient(_SCRIPTED_JSON)
    clf = CloudHeavyClassifier(client=fake)
    raw = clf.classify([_bgr_frame()], prompt="P")
    result = evaluate_classifier_output(raw, time_elapsed_seconds=0.5)
    assert result.ok
    assert result.payload is not None
    assert result.payload["tier"] == 3
    assert result.payload["behavior_pattern"] == "taking_item"


# ---------------------------------------------------------------------------
# CloudClothingDescriber
# ---------------------------------------------------------------------------


def test_clothing_describer_uses_caption_prompt_by_default() -> None:
    from vision_pipeline.qwen_captioner import CAPTION_PROMPT

    fake = _FakeAnthropicClient("tall man in red hoodie with a backpack")
    desc = CloudClothingDescriber(client=fake)
    out = desc(_bgr_frame())
    assert out == "tall man in red hoodie with a backpack"
    call = fake.messages.calls[0]
    content = call["messages"][0]["content"]
    assert content[-1]["type"] == "text"
    assert content[-1]["text"] == CAPTION_PROMPT
    # Single-image call.
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 1


def test_clothing_describer_plugs_into_qwen_captioner_cache() -> None:
    """The captioner should treat the cloud describer as just another
    callable and still cache by track id, so we never pay the cloud
    round-trip twice for the same person."""
    from vision_pipeline.qwen_captioner import QwenClothingCaptioner

    fake = _FakeAnthropicClient("person in green jacket")
    desc = CloudClothingDescriber(client=fake)

    cap = QwenClothingCaptioner(_describe=desc)
    out1 = cap(track_id=7, crop=_bgr_frame(1))
    out2 = cap(track_id=7, crop=_bgr_frame(2))
    assert out1 == "person in green jacket"
    assert out2 == out1
    # Cached → exactly one network call recorded.
    assert len(fake.messages.calls) == 1


def test_clothing_describer_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    desc = CloudClothingDescriber(api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        desc(_bgr_frame())
