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
