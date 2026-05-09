"""Person 2: VLM output validator acceptance tests.

Goal: be permissive about formatting, strict about safety.
"""

from vision_pipeline.events import (
    HALLUCINATED_LOCATIONS,
    LOW_VALUE_PHRASES,
    evaluate_classifier_output,
    parse_classifier_output,
)


def _wrap(payload_str: str) -> str:
    return payload_str


def test_accepts_plain_clean_json() -> None:
    raw = (
        '{"tier": 3, "confidence": 0.82, '
        '"suspect_description": "person carrying a black backpack", '
        '"one_line_summary": "person approaches porch with bag", '
        '"time_elapsed": "ignored"}'
    )
    result = evaluate_classifier_output(raw, 1.5)
    assert result.status == "accept", result.reason
    assert result.payload["tier"] == 3
    assert result.payload["time_elapsed"] == "1.50s"


def test_accepts_smart_quotes_and_code_fence() -> None:
    raw = (
        "```json\n"
        "{"
        "\u201ctier\u201d: 2, "
        "\u201cconfidence\u201d: 0.6, "
        "\u201csuspect_description\u201d: \u201cperson lingering near door\u201d, "
        "\u201cone_line_summary\u201d: \u201cperson stays at entry zone\u201d, "
        "\u201ctime_elapsed\u201d: \u201cignored\u201d"
        "}\n"
        "```"
    )
    result = evaluate_classifier_output(raw, 0.5)
    assert result.status == "accept", result.reason
    assert result.payload["tier"] == 2


def test_accepts_tier_as_string_label() -> None:
    raw = (
        '{"tier": "ALERT", "confidence": 90, '
        '"suspect_description": "person with bag", '
        '"one_line_summary": "person at porch with bag"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept", result.reason
    assert result.payload["tier"] == 3
    # 0..100 confidences get normalized into 0..1.
    assert 0.89 < result.payload["confidence"] <= 1.0


def test_accepts_alias_keys_summary_and_description() -> None:
    raw = (
        '{"tier": 1, "confidence": 0.4, '
        '"description": "person walks past", '
        '"summary": "passerby on sidewalk"}'
    )
    result = evaluate_classifier_output(raw, 0.25)
    assert result.status == "accept", result.reason


def test_accepts_trailing_commas() -> None:
    raw = (
        '{"tier": 3, "confidence": 0.7, '
        '"suspect_description": "person with backpack", '
        '"one_line_summary": "person near door with bag", '
        '"time_elapsed": "x",}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept", result.reason


def test_rejects_when_no_json_present() -> None:
    result = evaluate_classifier_output("just plain text, no json", 1.0)
    assert result.status == "reject"


def test_rejects_invalid_tier() -> None:
    raw = (
        '{"tier": 9, "confidence": 0.5, '
        '"suspect_description": "person", "one_line_summary": "thing", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "reject"


def test_rejects_when_description_mentions_indoor_location() -> None:
    raw = (
        '{"tier": 3, "confidence": 0.8, '
        '"suspect_description": "person reading in the library", '
        '"one_line_summary": "person inside library aisle", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "reject"
    assert "library" in result.reason


def test_rejects_when_summary_mentions_indoor_location() -> None:
    raw = (
        '{"tier": 3, "confidence": 0.8, '
        '"suspect_description": "person carrying bag", '
        '"one_line_summary": "person walks through office", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "reject"


def test_low_value_output_is_degraded_to_tier_one() -> None:
    raw = (
        '{"tier": 3, "confidence": 0.6, '
        '"suspect_description": "no person visible", '
        '"one_line_summary": "empty scene at entry zone", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "degrade"
    assert result.payload["tier"] == 1


def test_parse_classifier_output_returns_payload_for_accept_or_degrade() -> None:
    raw_accept = (
        '{"tier": 3, "confidence": 0.7, '
        '"suspect_description": "person with backpack", '
        '"one_line_summary": "person near door with bag", '
        '"time_elapsed": "x"}'
    )
    payload = parse_classifier_output(raw_accept, 1.0)
    assert payload is not None
    assert payload["tier"] == 3


def test_parse_classifier_output_returns_none_for_reject() -> None:
    payload = parse_classifier_output("not json", 1.0)
    assert payload is None


def test_constants_are_exported() -> None:
    # Helps ensure we don't accidentally drop the safety lists during refactors.
    assert "library" in HALLUCINATED_LOCATIONS
    assert "no event" in LOW_VALUE_PHRASES
