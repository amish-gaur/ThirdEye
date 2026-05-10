"""US-state recording-consent law lookup + disclosure preambles.

Recording laws differ by state. ThirdEye records both inbound and outbound
calls. In **two-party (all-party) consent** states, every party must be
notified before recording — we must play a disclosure preamble at the start
of every call where any party is in such a state. In **one-party consent**
states (and federally), only one party (us) needs to consent — but we still
play a soft disclosure for ethical reasons, just shorter.

Sources (general legal references; not legal advice):
- 18 U.S.C. § 2511 (federal one-party consent)
- State-specific eavesdropping / wiretapping statutes

We err on the side of caution: if the caller's state is unknown, we treat
the call as two-party consent.
"""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers
from phonenumbers import geocoder

# Two-party / all-party consent states.
# Conservative list — includes states where appellate caselaw treats consent
# as all-party even when the statute is ambiguous.
TWO_PARTY_CONSENT_STATES: frozenset[str] = frozenset(
    {
        "CA",  # Cal. Penal Code § 632
        "CT",  # Conn. Gen. Stat. § 52-570d (civil)
        "DE",  # Del. Code Ann. tit. 11, § 2402
        "FL",  # Fla. Stat. § 934.03
        "IL",  # 720 ILCS 5/14-2 (electronic communications)
        "MD",  # Md. Code Ann., Cts. & Jud. Proc. § 10-402
        "MA",  # Mass. Gen. Laws ch. 272, § 99
        "MI",  # Mich. Comp. Laws § 750.539c
        "MT",  # Mont. Code Ann. § 45-8-213
        "NV",  # Nev. Rev. Stat. § 200.620
        "NH",  # N.H. Rev. Stat. Ann. § 570-A:2
        "OR",  # Or. Rev. Stat. § 165.540 (electronic comm — in-person varies)
        "PA",  # 18 Pa. Cons. Stat. § 5704
        "WA",  # Wash. Rev. Code § 9.73.030
    }
)


@dataclass(frozen=True)
class JurisdictionInfo:
    state: str  # ISO subdivision suffix, e.g. "CA"; "" if unknown
    region: str  # "US-CA" or "US" if state unknown; "INTL" if non-US
    is_two_party: bool
    confidence: str  # "high" | "low" — area-code lookups are inherently low

    @property
    def jurisdiction_code(self) -> str:
        return self.region


def lookup_by_phone(e164: str) -> JurisdictionInfo:
    """Best-effort jurisdiction lookup from an E.164 number.

    Area codes are not a reliable signal of physical location (number
    portability), so we mark these as low confidence. The mobile onboarding
    flow asks the user to confirm their state during consent capture — that
    confirmation overrides this guess.
    """
    try:
        parsed = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return JurisdictionInfo("", "US", is_two_party=True, confidence="low")

    country = phonenumbers.region_code_for_number(parsed) or ""
    if country != "US":
        return JurisdictionInfo("", "INTL", is_two_party=True, confidence="low")

    # geocoder returns a description like "California". We translate to the
    # state code via a small lookup; if not found, default to two-party.
    description = geocoder.description_for_number(parsed, "en") or ""
    state = _STATE_NAME_TO_CODE.get(description.strip(), "")
    if not state:
        return JurisdictionInfo("", "US", is_two_party=True, confidence="low")
    return JurisdictionInfo(
        state=state,
        region=f"US-{state}",
        is_two_party=state in TWO_PARTY_CONSENT_STATES,
        confidence="low",
    )


def jurisdiction_for_state(state: str) -> JurisdictionInfo:
    """High-confidence path: user told us their state during onboarding."""
    state = (state or "").strip().upper()
    if len(state) != 2 or state not in _ALL_US_STATES:
        return JurisdictionInfo("", "US", is_two_party=True, confidence="high")
    return JurisdictionInfo(
        state=state,
        region=f"US-{state}",
        is_two_party=state in TWO_PARTY_CONSENT_STATES,
        confidence="high",
    )


def disclosure_preamble(info: JurisdictionInfo) -> str:
    """The disclosure spoken at the start of a call.

    We always play *some* disclosure — even in one-party states — because it
    builds trust. Two-party states get the explicit "this call may be
    recorded" wording; one-party states get a softer "ThirdEye is on this
    line" mention.
    """
    if info.is_two_party:
        return (
            "This is ThirdEye, a home security service. "
            "This call is being recorded for safety and quality. "
            "By staying on the line you consent to being recorded. "
            "If you do not consent, please hang up now."
        )
    return (
        "This is ThirdEye, a home security service. "
        "This call may be recorded for safety."
    )


def short_disclosure_preamble(info: JurisdictionInfo) -> str:
    """Compressed version for situations where a long preamble is hostile
    (e.g. immediate emergency tier-4 callouts)."""
    if info.is_two_party:
        return "ThirdEye on the line. This call is recorded; staying on the line is your consent."
    return "ThirdEye on the line. This call may be recorded."


# ---- internal ---------------------------------------------------------------

_STATE_NAME_TO_CODE: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

_ALL_US_STATES: frozenset[str] = frozenset(_STATE_NAME_TO_CODE.values()) | {"DC"}
