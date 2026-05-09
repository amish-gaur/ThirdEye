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


def test_sanitize_field_drops_hallucinated_locations() -> None:
    cleaned = sanitize_field("person carrying a bag in the library")
    assert "library" not in cleaned.lower()
    assert "person carrying a bag" in cleaned


def test_sanitize_event_provides_safe_defaults() -> None:
    out = sanitize_event({"tier": 3, "suspect_description": "", "one_line_summary": ""})
    assert out["suspect_description"] == "an unknown person"
    assert out["one_line_summary"] == "an event was detected at your home"


def test_static_template_strips_hallucinated_location() -> None:
    event = sample_event(
        tier=3,
        description="person reading in the library",
        summary="person browsing books in classroom",
    )
    text = static_template(event)
    lowered = text.lower()
    assert "library" not in lowered
    assert "classroom" not in lowered
    assert "Press 1" in text


def test_static_template_clamps_long_text() -> None:
    long_summary = "took a package " * 80
    event = sample_event(tier=3, summary=long_summary)
    text = static_template(event)
    assert len(text) <= MAX_SCRIPT_CHARS


def test_generate_script_uses_sanitized_static_when_claude_disabled(dry_config) -> None:
    event = sample_event(tier=3, description="person in classroom", summary="took a bag")
    script = generate_script(event, config=dry_config)
    assert "classroom" not in script.lower()
    assert "Press 1" in script


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
    assert "Press 1" in text
    assert "0." not in text  # no leaked confidence numbers
