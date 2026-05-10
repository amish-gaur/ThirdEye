"""Person 2: narration sanitization (defense in depth before TTS / Twilio Say)."""

from action_router.narration import (
    MAX_SCRIPT_CHARS,
    generate_script,
    sanitize_event,
    sanitize_field,
    static_template,
)
from scripts._fixtures import sample_event


def test_sanitize_field_strips_markdown_and_whitespace() -> None:
    assert sanitize_field("  **person** in   red `hoodie`  ") == "person in red hoodie"


def test_sanitize_field_keeps_location_words() -> None:
    """Location words like 'library' are now kept — Qwen describes the real scene."""
    cleaned = sanitize_field("person carrying a bag in the library")
    assert "library" in cleaned.lower()
    assert "person carrying a bag" in cleaned


def test_sanitize_event_provides_safe_defaults() -> None:
    out = sanitize_event({"tier": 3, "suspect_description": "", "one_line_summary": ""})
    assert out["suspect_description"] == "an unknown person"
    assert out["one_line_summary"] == "an event was detected at the camera view"
    # No scene supplied -> defaults to the camera view.
    assert out["scene"] == "the camera view"


def test_static_template_uses_scene_from_event() -> None:
    """Library demo: scene='the library entrance' should appear in the call."""
    event = sample_event(
        tier=3,
        description="tall person in a black shirt",
        summary="person reached toward an item on the table",
        scene="the library entrance",
    )
    text = static_template(event)
    assert "library entrance" in text.lower()
    assert "ThirdEye is watching." in text
    assert "Press 1" not in text


def test_static_template_falls_back_to_default_scene() -> None:
    """No scene field -> 'the camera view' instead of a hardcoded location."""
    event = sample_event(tier=3)
    event.pop("scene", None)
    text = static_template(event)
    assert "the camera view" in text.lower()
    assert "ThirdEye is watching." in text
    assert "Press 1" not in text


def test_static_template_clamps_long_text() -> None:
    long_summary = "took a package " * 80
    event = sample_event(tier=3, summary=long_summary)
    text = static_template(event)
    assert len(text) <= MAX_SCRIPT_CHARS


def test_generate_script_uses_sanitized_static_when_claude_disabled(dry_config) -> None:
    """Static fallback works for indoor scenes too (no more rejection)."""
    event = sample_event(
        tier=3,
        description="tall man in dark coat",
        summary="person took a bag from the table",
        scene="the office hallway",
    )
    script = generate_script(event, config=dry_config)
    assert "office hallway" in script.lower()
    assert "ThirdEye is watching." in script
    assert "Press 1" not in script


def test_generate_script_returns_empty_for_tier1(dry_config) -> None:
    assert generate_script(sample_event(tier=1), config=dry_config) == ""


# ---------------------------------------------------------------------------
# New: numeric scrubbing + YOLO-grounded fallback for generic descriptions
# ---------------------------------------------------------------------------


def test_sanitize_field_strips_numeric_artifacts() -> None:
    """'person 0.08' style leaks should never reach the call audio."""
    cleaned = sanitize_field("person 0.08 in red hoodie with backpack 0.85")
    lowered = cleaned.lower()
    # Numeric leaks gone, including the 'person N' wrapper that surrounds them.
    assert "0.08" not in lowered
    assert "0.85" not in lowered
    assert "person 0" not in lowered
    # Real descriptors survive.
    assert "red hoodie" in lowered
    assert "backpack" in lowered


def test_sanitize_field_strips_id_and_track_tokens() -> None:
    cleaned = sanitize_field("id 3 track_2 conf=0.9 person in blue jacket")
    lowered = cleaned.lower()
    assert "id 3" not in lowered
    assert "track_2" not in lowered
    assert "conf=0.9" not in lowered
    assert "blue jacket" in lowered


def test_sanitize_event_falls_back_to_yolo_classes_when_description_is_generic() -> None:
    """If VLM returned a generic description, we ground it in YOLO labels."""
    out = sanitize_event(
        {
            "tier": 3,
            "suspect_description": "a person",
            "one_line_summary": "person near the porch",
            "yolo_classes": ["person", "backpack"],
        }
    )
    assert out["suspect_description"] == "a person carrying a backpack"


def test_sanitize_event_yolo_fallback_with_two_carryables() -> None:
    out = sanitize_event(
        {
            "tier": 3,
            "suspect_description": "",
            "one_line_summary": "movement at the porch",
            "yolo_classes": ["person", "backpack", "handbag"],
        }
    )
    assert "person carrying" in out["suspect_description"]
    assert "backpack" in out["suspect_description"]


def test_sanitize_event_keeps_descriptive_text_unchanged() -> None:
    """A real, color-rich description should not be replaced."""
    out = sanitize_event(
        {
            "tier": 3,
            "suspect_description": "young man in a red hoodie and dark jeans",
            "one_line_summary": "person grabbed a package",
            "yolo_classes": ["person", "backpack"],
        }
    )
    assert "red hoodie" in out["suspect_description"]
    assert "backpack" not in out["suspect_description"]  # not enriched


def test_static_template_speaks_descriptive_features(dry_config) -> None:
    """End-to-end: descriptive event yields a call script with clothing details."""
    event = sample_event(
        tier=3,
        description="young man in a red hoodie and dark jeans",
        summary="person grabbed a package from the porch and walked off",
    )
    text = static_template(event)
    assert "red hoodie" in text
    assert "Press 1" not in text
    assert "0." not in text  # no leaked confidence numbers


def test_static_template_drops_trailing_lower_body_guess() -> None:
    event = sample_event(
        tier=3,
        description="short-haired person in a gray shirt and jeans",
        summary="person took an item from the table",
    )
    text = static_template(event)
    assert "gray shirt" in text
    assert "jeans" not in text
