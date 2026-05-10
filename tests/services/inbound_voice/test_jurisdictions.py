from __future__ import annotations

from services.inbound_voice.jurisdictions import (
    TWO_PARTY_CONSENT_STATES,
    disclosure_preamble,
    jurisdiction_for_state,
    short_disclosure_preamble,
)


def test_two_party_states_are_flagged_as_two_party() -> None:
    for state in TWO_PARTY_CONSENT_STATES:
        info = jurisdiction_for_state(state)
        assert info.is_two_party, f"{state} should be two-party"
        assert info.region == f"US-{state}"
        assert info.confidence == "high"


def test_one_party_states_are_flagged_correctly() -> None:
    for state in ("NY", "TX", "VA", "CO", "GA"):
        info = jurisdiction_for_state(state)
        assert not info.is_two_party, f"{state} should be one-party"


def test_unknown_state_defaults_to_two_party_for_safety() -> None:
    info = jurisdiction_for_state("ZZ")
    assert info.is_two_party
    assert info.region == "US"


def test_disclosure_preambles_mention_recording_in_two_party_states() -> None:
    info = jurisdiction_for_state("CA")
    long = disclosure_preamble(info)
    short = short_disclosure_preamble(info)
    assert "recorded" in long.lower()
    assert "recorded" in short.lower()
    assert "consent" in long.lower()


def test_disclosure_preambles_are_softer_in_one_party_states() -> None:
    info = jurisdiction_for_state("TX")
    long = disclosure_preamble(info)
    short = short_disclosure_preamble(info)
    # Still mentions SafeWatch and possibility of recording
    assert "SafeWatch" in long
    assert "may be recorded" in long.lower()
    assert "consent" not in long.lower()  # No mandatory consent language
    assert "may be recorded" in short.lower()
