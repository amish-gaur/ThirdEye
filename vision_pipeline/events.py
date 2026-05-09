"""Shared event schema + classifier output parsing for the vision side.

Person 2 ownership:
- VLM prompt
- output parser / validator (permissive but safe)
- acceptance rules (ACCEPT / DEGRADE / REJECT) so the engine can act appropriately

Validator philosophy:
- Be generous with shape (smart quotes, code fences, single quotes, missing keys
  with sane defaults).
- Be strict on safety (tier 1..4, no hallucinated indoor locations like "library"
  / "office", confidence clamped to [0, 1]).
"""

from __future__ import annotations

import ast
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Prompt sent to the VLM (Qwen / Moondream). Tight, explicit, JSON-only.
# ---------------------------------------------------------------------------

VISION_LANGUAGE_PROMPT = """You are a calm, factual neighborhood security classifier.

Look at the scene and decide a severity tier from this list:
  1 = AMBIENT   (passerby, normal activity, nothing notable)
  2 = NOTICE    (loitering, unusual presence, no immediate threat)
  3 = ALERT     (likely theft / trespass / suspicious interaction with property)
  4 = EMERGENCY (collapse, injury, fire, smoke, violence)

OUTPUT RULES (strict):
- Reply with ONE JSON object and NOTHING else. No prose, no markdown, no code fences.
- Keys (all required):
    "tier": integer in {1,2,3,4}
    "confidence": float in [0.0, 1.0]
    "suspect_description": short factual phrase (<= 18 words). Describe ONLY what
        is visible (clothing color, item being carried, posture). Do NOT invent
        names, ages, ethnicities, indoor rooms, or context you cannot see.
    "one_line_summary": short factual sentence (<= 20 words) about the BEHAVIOR.
    "time_elapsed": short string (will be overwritten by the pipeline).

DO NOT name indoor places (library, classroom, office, kitchen, bedroom, store,
restaurant, mall, school, hospital, church). This is an outdoor home camera.

If unsure, choose tier 1 with low confidence.
"""

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

REQUIRED_CLASSIFIER_KEYS = {
    "tier",
    "confidence",
    "suspect_description",
    "one_line_summary",
    "time_elapsed",
}

# Words/phrases that indicate the VLM is hallucinating an indoor scene/context
# the home camera cannot actually see. These cause REJECT (or DEGRADE to tier 1).
HALLUCINATED_LOCATIONS = (
    "library",
    "classroom",
    "school",
    "office",
    "kitchen",
    "bedroom",
    "bathroom",
    "living room",
    "store",
    "supermarket",
    "mall",
    "restaurant",
    "cafeteria",
    "hospital",
    "church",
    "temple",
    "mosque",
    "stadium",
    "gym",
    "factory",
    "warehouse",
    "subway",
    "airport",
)

# Soft signals — descriptions like these are uselessly vague; we keep them but
# tag them so callers can choose to suppress the alert or relabel it tier 1.
LOW_VALUE_PHRASES = (
    "no event",
    "nothing unusual",
    "normal scene",
    "no person",
    "empty scene",
)

MAX_DESCRIPTION_WORDS = 24
MAX_SUMMARY_WORDS = 28


# ---------------------------------------------------------------------------
# Acceptance result (so engine can ACCEPT, DEGRADE to tier 1, or REJECT outright).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    status: str  # "accept" | "degrade" | "reject"
    payload: dict[str, Any] | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.status in {"accept", "degrade"}


def evaluate_classifier_output(
    raw_text: str, time_elapsed_seconds: float
) -> ClassificationResult:
    """Parse + validate raw VLM output and return a structured ClassificationResult.

    - "reject" : malformed / missing keys / forbidden hallucinated locations.
    - "degrade": parsable but uselessly vague — kept at tier 1 so the router logs only.
    - "accept" : safe to forward to the router as-is.
    """

    json_blob = extract_json_object(raw_text)
    if json_blob is None:
        return ClassificationResult("reject", None, "no JSON object in VLM output")

    raw_payload = _load_structured_payload(json_blob)
    if raw_payload is None:
        return ClassificationResult("reject", None, "JSON did not parse to an object")

    payload = _normalize_classifier_payload(raw_payload, time_elapsed_seconds)
    if payload is None:
        return ClassificationResult(
            "reject", None, "missing required keys / invalid types"
        )

    bad_word = _contains_hallucinated_location(payload)
    if bad_word:
        return ClassificationResult(
            "reject", None, f"hallucinated indoor location: {bad_word!r}"
        )

    if _is_low_value(payload):
        payload["tier"] = 1
        return ClassificationResult(
            "degrade", payload, "low-value content; degraded to tier 1"
        )

    return ClassificationResult("accept", payload, "ok")


# Backwards-compatible thin wrapper. Returns the payload dict on accept/degrade,
# else None. New callers should prefer evaluate_classifier_output().
def parse_classifier_output(
    raw_text: str, time_elapsed_seconds: float
) -> dict[str, Any] | None:
    result = evaluate_classifier_output(raw_text, time_elapsed_seconds)
    return result.payload if result.ok else None


def build_event(
    *,
    classification: dict[str, Any],
    node_id: str,
    frame_seq: int,
    yolo_classes: list[str],
    raw_classifier: str,
    timestamp: float | None = None,
) -> dict[str, Any]:
    tier = int(classification["tier"])
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "node_id": node_id,
        "tier": tier,
        "tier_name": TIER_LABELS.get(tier, "UNKNOWN"),
        "confidence": float(classification["confidence"]),
        "suspect_description": classification["suspect_description"],
        "one_line_summary": classification["one_line_summary"],
        "time_elapsed": classification["time_elapsed"],
        "timestamp": timestamp if timestamp is not None else time.time(),
        "frame_seq": frame_seq,
        "yolo_classes": sorted(set(yolo_classes)),
        "clip_hash": None,
        "raw_classifier": raw_classifier,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Smart quotes and similar Unicode oddities VLMs sometimes emit.
_QUOTE_FIXES = {
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201e": '"',
}


def _strip_smart_quotes(text: str) -> str:
    for bad, good in _QUOTE_FIXES.items():
        text = text.replace(bad, good)
    return text


def extract_json_object(raw_text: str) -> str | None:
    if not raw_text:
        return None
    cleaned = _strip_smart_quotes(raw_text).strip()
    cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    return match.group(0)


def _load_structured_payload(blob: str) -> dict[str, Any] | None:
    candidates = [blob, _drop_trailing_commas(blob)]
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                payload = ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                continue
        if isinstance(payload, dict):
            return payload
    return None


def _drop_trailing_commas(blob: str) -> str:
    return re.sub(r",\s*([\]}])", r"\1", blob)


def _coerce_tier(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
    elif isinstance(value, str):
        text = value.strip().upper()
        for tier_int, label in TIER_LABELS.items():
            if text == label or text == str(tier_int):
                return tier_int
        try:
            n = int(float(text))
        except ValueError:
            return None
    else:
        return None
    return n if n in {1, 2, 3, 4} else None


def _coerce_confidence(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return 0.0
    if f > 1:
        # Some models output 0..100; normalize.
        if f <= 100:
            return min(1.0, f / 100.0)
        return 1.0
    return f


def _trim_words(text: str, max_words: int) -> str:
    words = text.strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",.;:") + "..."


def _normalize_classifier_payload(
    payload: dict[str, Any], time_elapsed_seconds: float
) -> dict[str, Any] | None:
    # Allow common alias keys for friendliness.
    if "summary" in payload and "one_line_summary" not in payload:
        payload["one_line_summary"] = payload["summary"]
    if "description" in payload and "suspect_description" not in payload:
        payload["suspect_description"] = payload["description"]
    payload.setdefault("time_elapsed", "ignored")

    if not REQUIRED_CLASSIFIER_KEYS.issubset(payload.keys()):
        return None

    tier = _coerce_tier(payload["tier"])
    if tier is None:
        return None

    confidence = _coerce_confidence(payload["confidence"])
    if confidence is None:
        return None

    desc = payload["suspect_description"]
    summary = payload["one_line_summary"]
    elapsed = payload["time_elapsed"]
    if not isinstance(desc, str) or not isinstance(summary, str) or not isinstance(elapsed, str):
        return None

    desc = _trim_words(desc, MAX_DESCRIPTION_WORDS)
    summary = _trim_words(summary, MAX_SUMMARY_WORDS)

    if not desc or not summary:
        return None

    return {
        "tier": tier,
        "confidence": confidence,
        "suspect_description": desc,
        "one_line_summary": summary,
        "time_elapsed": f"{time_elapsed_seconds:.2f}s",
    }


def _contains_hallucinated_location(payload: dict[str, Any]) -> str | None:
    for field in ("suspect_description", "one_line_summary"):
        text = payload.get(field, "").lower()
        for word in HALLUCINATED_LOCATIONS:
            if re.search(rf"\b{re.escape(word)}\b", text):
                return word
    return None


def _is_low_value(payload: dict[str, Any]) -> bool:
    blob = (
        payload.get("suspect_description", "") + " " + payload.get("one_line_summary", "")
    ).lower()
    return any(phrase in blob for phrase in LOW_VALUE_PHRASES)
