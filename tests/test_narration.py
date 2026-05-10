from action_router.narration import build_user_prompt, generate_script, static_template
from scripts._fixtures import sample_event


def test_static_template_tier1_is_empty() -> None:
    assert static_template(sample_event(tier=1)) == ""


def test_static_template_tier3_uses_thirdeye_alert_language() -> None:
    text = static_template(sample_event(tier=3))
    assert "ThirdEye is watching." in text
    assert "Press 1" not in text
    assert "active alert" in text.lower()


def test_static_template_tier4_mentions_emergency() -> None:
    text = static_template(sample_event(tier=4))
    assert "Emergency services" in text or "emergency services" in text.lower()


def test_build_user_prompt_includes_all_fields() -> None:
    event = sample_event(tier=3, description="red hoodie", summary="took package")
    prompt = build_user_prompt(event)
    assert "tier: 3 (ALERT)" in prompt
    assert "red hoodie" in prompt
    assert "took package" in prompt


def test_generate_script_falls_back_when_claude_disabled(dry_config) -> None:
    event = sample_event(tier=3)
    script = generate_script(event, config=dry_config)
    assert "ThirdEye is watching." in script
    assert "Press 1" not in script
