"""Person 2: router dedup + voice safety tests."""

import pytest

from action_router.router import execute_action, reset_dedup_cache
from action_router.voice import (
    SAY_TEXT_MAX_CHARS,
    VoiceError,
    _clamp_say,
    _validate_to,
    place_call_say,
)
from scripts._fixtures import sample_event


@pytest.fixture(autouse=True)
def _clear_dedup() -> None:
    reset_dedup_cache()
    yield
    reset_dedup_cache()


def test_router_deduplicates_same_event_id_within_window(dry_config) -> None:
    event = sample_event(tier=3)
    first = execute_action(event, config=dry_config)
    assert not first.duplicate
    assert "call_homeowner" in first.actions

    second = execute_action(event, config=dry_config)
    assert second.duplicate
    assert second.actions == ["dedup_skip"]
    assert not second.calls


def test_router_does_not_dedup_when_event_id_missing(dry_config) -> None:
    event = sample_event(tier=3)
    event.pop("event_id")
    first = execute_action(event, config=dry_config)
    second = execute_action(event, config=dry_config)
    assert not first.duplicate
    assert not second.duplicate


def test_router_coerces_string_tier_label(dry_config) -> None:
    event = sample_event(tier=3)
    event["tier"] = "ALERT"
    result = execute_action(event, config=dry_config)
    assert result.tier == 3
    assert "call_homeowner" in result.actions


def test_router_coerces_numeric_string_tier(dry_config) -> None:
    event = sample_event(tier=2)
    event["tier"] = "2"
    result = execute_action(event, config=dry_config)
    assert result.tier == 2


def test_router_clamps_out_of_range_tier(dry_config) -> None:
    event = sample_event(tier=4)
    event["tier"] = 99
    result = execute_action(event, config=dry_config)
    assert result.tier == 4  # clamped, not rejected


def test_voice_validate_to_rejects_garbage() -> None:
    with pytest.raises(VoiceError):
        _validate_to("not a number")


def test_voice_validate_to_accepts_e164() -> None:
    assert _validate_to("+15555550100") == "+15555550100"


def test_voice_clamp_say_truncates_long_text() -> None:
    long_text = "alert " * 500
    clamped = _clamp_say(long_text)
    assert len(clamped) <= SAY_TEXT_MAX_CHARS


def test_voice_clamp_say_collapses_whitespace() -> None:
    assert _clamp_say("   hello    world  ") == "hello world"


def test_voice_clamp_say_returns_default_on_empty() -> None:
    assert _clamp_say("") == "SafeWatch alert."


def test_place_call_say_dry_run_validates_to(dry_config) -> None:
    with pytest.raises(VoiceError):
        place_call_say("garbage", "hello", config=dry_config)


def test_place_call_say_dry_run_returns_dryrun(dry_config) -> None:
    result = place_call_say("+15555550100", "hello world", config=dry_config)
    assert result.dry_run
    assert result.sid == "DRYRUN"
    assert "hello world" in result.twiml
