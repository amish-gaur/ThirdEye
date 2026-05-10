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
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.82, '
        '"suspect_description": "young man in black jacket carrying a backpack", '
        '"one_line_summary": "person took a package from the porch and walked off", '
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
        "\u201cbehavior_pattern\u201d: \u201cloitering\u201d, "
        "\u201cconfidence\u201d: 0.6, "
        "\u201csuspect_description\u201d: \u201cman in red hoodie lingering near door\u201d, "
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
        '{"tier": "ALERT", "behavior_pattern": "taking_item", "confidence": 90, '
        '"suspect_description": "young woman in green jacket with backpack", '
        '"one_line_summary": "person grabbed a package from the porch"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept", result.reason
    assert result.payload["tier"] == 3
    # 0..100 confidences get normalized into 0..1.
    assert 0.89 < result.payload["confidence"] <= 1.0


def test_accepts_alias_keys_summary_and_description() -> None:
    raw = (
        '{"tier": 1, "behavior_pattern": "walking_through", "confidence": 0.4, '
        '"description": "young woman in blue jacket walking past", '
        '"summary": "passerby on sidewalk"}'
    )
    result = evaluate_classifier_output(raw, 0.25)
    assert result.status == "accept", result.reason


def test_accepts_trailing_commas() -> None:
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.7, '
        '"suspect_description": "young man in black hoodie with backpack", '
        '"one_line_summary": "person reached for a package on the porch", '
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


def test_indoor_descriptions_are_now_accepted_with_scene() -> None:
    """Indoor scenes are valid (library, office, parking lot) — Qwen describes
    the actual location now instead of being forced to assume an outdoor home."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"scene": "the library aisle", '
        '"suspect_description": "tall man in a black shirt and gray jeans", '
        '"one_line_summary": "person reached for a backpack on the table", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept", result.reason
    assert result.payload["scene"] == "the library aisle"


def test_office_scene_is_accepted() -> None:
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"scene": "office hallway", '
        '"suspect_description": "person in dark coat with backpack", '
        '"one_line_summary": "person picked up an item from the floor", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    # Auto-prepends "the" if missing.
    assert result.payload["scene"] == "the office hallway"


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
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.7, '
        '"suspect_description": "young man in red hoodie with backpack", '
        '"one_line_summary": "person reached for a package on the porch", '
        '"time_elapsed": "x"}'
    )
    payload = parse_classifier_output(raw_accept, 1.0)
    assert payload is not None
    assert payload["tier"] == 3


def test_parse_classifier_output_returns_none_for_reject() -> None:
    payload = parse_classifier_output("not json", 1.0)
    assert payload is None


def test_constants_are_exported() -> None:
    # HALLUCINATED_LOCATIONS is intentionally empty now — we accept indoor scenes.
    assert HALLUCINATED_LOCATIONS == ()
    assert "no event" in LOW_VALUE_PHRASES


def test_scene_field_default_is_camera_view() -> None:
    """If Qwen omits scene, default to 'the camera view' instead of crashing."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"suspect_description": "tall man in a black shirt", '
        '"one_line_summary": "person reached for an item", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["scene"] == "the camera view"


def test_scene_alias_keys_normalized() -> None:
    """Accept 'location' or 'setting' as aliases for 'scene'."""
    raw_location = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"location": "parking lot", '
        '"suspect_description": "tall man in a dark coat", '
        '"one_line_summary": "person grabbed an item from a vehicle", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw_location, 1.0)
    assert result.payload["scene"] == "the parking lot"


# ---------------------------------------------------------------------------
# behavior_pattern guard + numeric scrubbing
# ---------------------------------------------------------------------------


def test_tier3_with_benign_pattern_is_clamped_to_ambient() -> None:
    """Person walking through with a backpack should never call the homeowner."""
    raw = (
        '{"tier": 3, "behavior_pattern": "walking_through", "confidence": 0.9, '
        '"suspect_description": "young man in red hoodie carrying a backpack", '
        '"one_line_summary": "person walked past the porch", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "degrade"
    assert result.payload["tier"] == 1
    assert "walking_through" in result.reason


def test_tier3_with_loitering_is_passed_through_for_router_to_decide() -> None:
    """Loitering is no longer auto-clamped at the validator. The router's
    confidence floor + tier mapping handles non-theft patterns; this lets
    Qwen tier-up legitimately ambiguous cases."""
    raw = (
        '{"tier": 3, "behavior_pattern": "loitering", "confidence": 0.7, '
        '"suspect_description": "young woman in green jacket near the door", '
        '"one_line_summary": "person stood near the porch for several minutes", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["tier"] == 3
    assert result.payload["behavior_pattern"] == "loitering"


def test_tier3_taking_item_is_accepted() -> None:
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"suspect_description": "young man in black hoodie with backpack", '
        '"one_line_summary": "person picked up a package and walked away", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["tier"] == 3


def test_tier4_violence_is_accepted() -> None:
    raw = (
        '{"tier": 4, "behavior_pattern": "violence", "confidence": 0.85, '
        '"suspect_description": "two men in dark jackets shoving each other", '
        '"one_line_summary": "physical altercation in the driveway", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["tier"] == 4


def test_tier3_without_visual_descriptor_still_accepted_router_handles_it() -> None:
    """The visual-descriptor clamp was killing real demos when Qwen played
    safe with vague wording. We now accept and let the router/narration
    enrich descriptions from YOLO labels if needed."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"suspect_description": "subject took the item", '
        '"one_line_summary": "subject took the item near the entryway", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["tier"] == 3


def test_numeric_artifacts_are_scrubbed_from_description() -> None:
    """'person 0.08' style leaks from the VLM are removed."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.8, '
        '"suspect_description": "person 0.08 in red hoodie with backpack", '
        '"one_line_summary": "person 1 0.85 took a package", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    desc = result.payload["suspect_description"]
    summary = result.payload["one_line_summary"]
    assert "0.08" not in desc and "0.08" not in summary
    assert "person 0" not in desc.lower() and "person 1" not in summary.lower()
    assert "red hoodie" in desc and "backpack" in desc


def test_id_and_track_artifacts_are_scrubbed() -> None:
    raw = (
        '{"tier": 2, "behavior_pattern": "loitering", "confidence": 0.5, '
        '"suspect_description": "id 3 track_2 person in blue jacket", '
        '"one_line_summary": "subject in blue jacket lingered", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    desc = result.payload["suspect_description"]
    assert "id 3" not in desc.lower()
    assert "track_2" not in desc.lower()
    assert "blue jacket" in desc


def test_person_no_dot_n_format_is_scrubbed() -> None:
    """'Person No. 1 (0.85)' from over-eager VLMs gets fully cleaned."""
    raw = (
        '{"tier": 2, "behavior_pattern": "loitering", "confidence": 0.5, '
        '"suspect_description": "Person No. 1 (0.85) in dark jacket", '
        '"one_line_summary": "Person #2 0.7 lingered near the door", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    desc = result.payload["suspect_description"].lower()
    summary = result.payload["one_line_summary"].lower()
    for needle in ("0.85", "0.7", "person no", "person #", "(0.", "()"):
        assert needle not in desc, (needle, desc)
        assert needle not in summary, (needle, summary)
    assert "dark jacket" in desc
    assert "lingered" in summary


def test_bare_decimals_anywhere_are_scrubbed() -> None:
    """Stray numeric tokens are removed even without a 'person' anchor."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.7, '
        '"suspect_description": "tall man 0.85 in black shirt and 0.62 gray jeans", '
        '"one_line_summary": "subject 0.5 reached for the package 0.3", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    for field in ("suspect_description", "one_line_summary"):
        text = result.payload[field]
        assert "0.85" not in text and "0.62" not in text
        assert "0.5" not in text and "0.3" not in text


def test_truthful_description_passes_through_unchanged() -> None:
    """Real, well-formed descriptions are NOT mangled by the scrubber."""
    raw = (
        '{"tier": 3, "behavior_pattern": "taking_item", "confidence": 0.7, '
        '"suspect_description": "tall man wearing a black shirt and gray jeans", '
        '"one_line_summary": "person reached down and picked up an item from the porch", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    assert result.payload["suspect_description"] == "tall man wearing a black shirt and gray jeans"
    assert "picked up an item" in result.payload["one_line_summary"]


def test_behavior_pattern_aliases_normalized() -> None:
    raw = (
        '{"tier": 3, "behavior_pattern": "stealing", "confidence": 0.8, '
        '"suspect_description": "young man in red hoodie with backpack", '
        '"one_line_summary": "person grabbed a package and ran", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.payload is not None
    assert result.payload["behavior_pattern"] == "taking_item"


def test_missing_behavior_pattern_does_not_clamp_tier() -> None:
    """When Qwen omits behavior_pattern we no longer auto-clamp to tier 1.
    The previous behavior was killing legitimate alerts when the model
    forgot the field. Pattern defaults to 'other_benign' for downstream
    template lookup but the tier from Qwen is honored."""
    raw = (
        '{"tier": 3, "confidence": 0.7, '
        '"suspect_description": "young man in red hoodie", '
        '"one_line_summary": "person near the porch", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "accept"
    assert result.payload["tier"] == 3
    assert result.payload["behavior_pattern"] == "other_benign"


def test_explicit_walking_through_at_tier3_is_clamped() -> None:
    """The clamp DOES still apply when Qwen explicitly chose a benign pattern."""
    raw = (
        '{"tier": 3, "behavior_pattern": "walking_through", "confidence": 0.9, '
        '"suspect_description": "young woman in green jacket carrying a backpack", '
        '"one_line_summary": "person walked past the porch", '
        '"time_elapsed": "x"}'
    )
    result = evaluate_classifier_output(raw, 1.0)
    assert result.status == "degrade"
    assert result.payload["tier"] == 1
