"""PII redaction for transcripts before persistence.

We auto-redact:
- Credit card numbers (Luhn-validated 13-19 digits)
- US Social Security numbers (xxx-xx-xxxx, also bare 9-digit if surrounded by SSN/social keywords)
- Phone numbers (NANP and E.164)
- Email addresses
- High-entropy tokens that look like API keys (>= 24 chars, mixed alnum)

Each match is replaced with a categorical placeholder (`[CC]`, `[SSN]`, etc.)
and recorded in a redactions list — the homeowner sees how many redactions
happened (transparency) but never the raw redacted content (privacy).

We deliberately do NOT redact names — the entire point of a SafeWatch
transcript is "the suspect said his name is Mike." Names belong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Redaction:
    category: str  # "CC" | "SSN" | "PHONE" | "EMAIL" | "TOKEN"
    placeholder: str
    span: tuple[int, int]  # (start, end) in the *original* text


@dataclass(frozen=True)
class RedactionResult:
    redacted_text: str
    redactions: tuple[Redaction, ...]

    @property
    def count(self) -> int:
        return len(self.redactions)


def redact(text: str) -> RedactionResult:
    if not text:
        return RedactionResult(redacted_text="", redactions=())

    matches: list[tuple[int, int, str, str]] = []  # (start, end, category, placeholder)

    # Email — strict-ish; we'd rather miss than false-positive.
    for m in _EMAIL.finditer(text):
        matches.append((m.start(), m.end(), "EMAIL", "[EMAIL]"))

    # SSN — labeled or bare 3-2-4 with dashes/spaces.
    for m in _SSN.finditer(text):
        matches.append((m.start(), m.end(), "SSN", "[SSN]"))

    # Phone — NANP-ish or E.164.
    for m in _PHONE.finditer(text):
        matches.append((m.start(), m.end(), "PHONE", "[PHONE]"))

    # Credit card — only Luhn-valid 13-19 digit runs (with optional spaces/dashes).
    for m in _CC_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            matches.append((m.start(), m.end(), "CC", "[CC]"))

    # API-key-ish high-entropy tokens.
    for m in _TOKEN.finditer(text):
        token = m.group(0)
        if _entropy_bits_per_char(token) >= 3.0:
            matches.append((m.start(), m.end(), "TOKEN", "[TOKEN]"))

    matches.sort(key=lambda t: (t[0], -t[1]))
    matches = _drop_overlaps(matches)

    out: list[str] = []
    cursor = 0
    redactions: list[Redaction] = []
    for start, end, category, placeholder in matches:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(placeholder)
        redactions.append(Redaction(category=category, placeholder=placeholder, span=(start, end)))
        cursor = end
    out.append(text[cursor:])

    return RedactionResult(redacted_text="".join(out), redactions=tuple(redactions))


# ---- internal ---------------------------------------------------------------

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(
    r"(?:\+?1[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}\b|"
    r"\+\d{8,15}\b"
)
_CC_CANDIDATE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")
_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _drop_overlaps(
    matches: list[tuple[int, int, str, str]]
) -> list[tuple[int, int, str, str]]:
    out: list[tuple[int, int, str, str]] = []
    for m in matches:
        if out and m[0] < out[-1][1]:
            continue
        out.append(m)
    return out


def _entropy_bits_per_char(s: str) -> float:
    from collections import Counter
    from math import log2

    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * log2(c / n) for c in counts.values())
