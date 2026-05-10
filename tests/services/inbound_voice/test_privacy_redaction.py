from __future__ import annotations

from services.inbound_voice.privacy.redaction import redact


def test_empty_text_returns_empty() -> None:
    result = redact("")
    assert result.redacted_text == ""
    assert result.redactions == ()


def test_email_redaction() -> None:
    result = redact("Contact me at jane.doe@example.com tomorrow.")
    assert "[EMAIL]" in result.redacted_text
    assert "jane.doe@example.com" not in result.redacted_text
    assert result.count == 1
    assert result.redactions[0].category == "EMAIL"


def test_ssn_redaction() -> None:
    result = redact("My SSN is 123-45-6789, please don't share.")
    assert "[SSN]" in result.redacted_text
    assert "123-45-6789" not in result.redacted_text


def test_phone_redaction() -> None:
    result = redact("Call me at (415) 555-0123 or +14155550123.")
    assert result.redacted_text.count("[PHONE]") == 2
    assert "555" not in result.redacted_text


def test_credit_card_only_when_luhn_valid() -> None:
    # 4242 4242 4242 4242 is the Stripe test card — Luhn-valid.
    valid = redact("Card is 4242 4242 4242 4242 here.")
    assert "[CC]" in valid.redacted_text

    # 16 random digits that fail Luhn — must NOT be redacted as CC.
    invalid = redact("Order number 1234567890123456 is queued.")
    assert "[CC]" not in invalid.redacted_text


def test_high_entropy_token_redaction() -> None:
    result = redact("API key: sk_live_4ZxRtN2qG7vH8mLk3PwYbX9aEcD6jUn0tF1sV5oA")
    assert "[TOKEN]" in result.redacted_text


def test_low_entropy_long_strings_are_not_redacted_as_tokens() -> None:
    # Ordinary long words shouldn't trigger TOKEN redaction.
    result = redact("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa is just letters.")
    categories = {r.category for r in result.redactions}
    assert "TOKEN" not in categories


def test_names_are_preserved() -> None:
    result = redact("The suspect said his name is Mike Johnson.")
    assert "Mike Johnson" in result.redacted_text
    assert result.count == 0


def test_overlapping_matches_resolve_without_corruption() -> None:
    # Email contains characters that other patterns might also see.
    result = redact("foo@bar.com 1234567890")
    assert "[EMAIL]" in result.redacted_text
    assert "foo@bar.com" not in result.redacted_text


def test_multiple_categories_in_one_message() -> None:
    text = "Email me at me@x.com or call (555) 555-1234, SSN 999-99-9999."
    result = redact(text)
    cats = {r.category for r in result.redactions}
    assert {"EMAIL", "PHONE", "SSN"}.issubset(cats)
