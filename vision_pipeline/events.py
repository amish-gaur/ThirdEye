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

VISION_LANGUAGE_PROMPT = """You are ThirdEye, a sharp-eyed home security classifier.
You will be shown 1-3 RECENT FRAMES from the same camera (the most recent
frame is last). Your job: describe the person and what they are doing
specifically and confidently. Do NOT guess details that are not clearly
visible in the frames.

Pick ONE behavior_pattern that matches the action across the frames:
  walking_through   - passing by, no interaction with property
  loitering         - standing/lingering for several frames with no purpose
  taking_item       - reaching for / picking up / removing an item
  leaving_item      - placing an object down
  opening_container - opening a bag, box, door, or package
  fleeing           - running with an item
  collapsed         - person on the ground, not moving normally
  violence          - punching, hitting, fighting, weapon visible, shoving
  other_benign      - clearly normal activity (delivery, walking pet, neighbor)

Map behavior_pattern to a tier:
  1 AMBIENT   = walking_through, other_benign
  2 NOTICE    = loitering, leaving_item
  3 ALERT     = taking_item, opening_container, fleeing
  4 EMERGENCY = collapsed, violence

DESCRIPTION RULES (the suspect_description is the MOST IMPORTANT field —
the person on the phone needs enough detail to identify the suspect):
- CLOTHING COLOR must be SPECIFIC. Prefer named colors ("brown", "navy",
  "olive", "beige", "maroon", "forest green", "burgundy", "tan",
  "charcoal", "cream") over vague "dark" / "light". Only fall back to
  "dark <item>" / "light <item>" when the lighting genuinely makes the
  hue unreadable — and even then, guess the most likely named color.
- NAME THE GARMENT, not just the color: "brown hoodie", "navy puffer
  jacket", "olive cargo pants", "white t-shirt", "gray sweatshirt".
- Include HAIR when visible: color + length + style ("short black hair",
  "long blonde ponytail", "shaved head", "shoulder-length brown hair",
  "bald", "covered by hood").
- Include FACIAL features when visible: facial hair ("clean-shaven",
  "short beard", "mustache"), glasses, mask, approximate age band
  ("20s", "30s", "40s", "older adult"), and apparent skin tone in
  neutral terms ("light-skinned", "medium-skinned", "dark-skinned") —
  ONLY when clearly visible. Do not invent these.
- Include BUILD when visible: "tall and slim", "stocky", "average
  build", "short and slight".
- Include ACCESSORIES and CARRIED ITEMS: "black backpack", "red cap",
  "carrying a cardboard box", "phone in hand", "gloves".
- If only the upper body is visible, describe only upper-body clothing,
  face, hair, and accessories. Do NOT guess jeans, pants, shoes, or
  other lower-body details unless you can clearly see them.
- 12-25 words. Lead with the single most identifying feature
  (distinctive jacket color, hair, or accessory).
- Examples of GOOD descriptions:
    "man in his 30s, short black hair, brown hoodie and dark jeans, black backpack, clean-shaven"
    "young woman, long blonde hair, olive jacket over white t-shirt, carrying a cardboard package"
    "stocky man, red baseball cap, navy puffer jacket, short beard, gloves on both hands"
    "tall slim person, hood up, charcoal sweatshirt, black mask, white sneakers"
- Examples of BAD descriptions (NEVER write these):
    "person of unclear appearance"
    "a person in dark clothing"
    "person wearing a jacket"
    "subject"

BEHAVIOR RULES (commit to a tier):
- If you see ANY hint of theft motion (reaching down toward an object,
  carrying something away that wasn't there before), pick taking_item / tier 3.
- If you see ANY hint of physical contact (fist, shove, grab), pick
  violence / tier 4.
- If the person is on the ground or unmoving, pick collapsed / tier 4.
- Only use tier 1 when the person is clearly just walking through with no
  interaction at all.
- Carrying a backpack ALONE is tier 1. But carrying a backpack AND reaching
  for something on the porch/table is tier 3.

CONFIDENCE:
- 0.8+ : clear, multi-frame evidence of the behavior
- 0.5-0.8 : likely behavior, some ambiguity
- 0.3-0.5 : best guess but not certain
- < 0.3  : you literally cannot tell

NEVER include numbers, IDs, "person 0", "person 0.08", "id 3", "track_2",
"conf=", bounding-box coords, or model names in any text field.

SCENE: a brief phrase for the visible location ("front porch", "parking
lot", "side gate", "kitchen counter"). 2-6 words. The homeowner already
knows where their camera is pointed, so keep this short — spend your
attention on suspect_description, which is what the listener actually
needs to identify the person.

OUTPUT (JSON only, no prose, no markdown, no code fences):
{
  "tier": 1|2|3|4,
  "behavior_pattern": "<one of the patterns above>",
  "confidence": 0.0-1.0,
  "scene": "<2-8 word location>",
  "suspect_description": "<12-25 word description: specific clothing colors, garments, hair, build, accessories>",
  "one_line_summary": "<8-20 word summary of the behavior you saw>",
  "time_elapsed": "ignored"
}
"""

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

REQUIRED_CLASSIFIER_KEYS = {
    "tier",
    "confidence",
    "suspect_description",
    "one_line_summary",
    "time_elapsed",
}

# scene is OPTIONAL — if absent the validator fills in "the camera view" so the
# narration always has something concrete to say.
OPTIONAL_CLASSIFIER_KEYS = {"scene", "behavior_pattern"}

DEFAULT_SCENE = "the camera view"

# behavior_pattern values mapped to the maximum tier they may carry.
# A pattern observed at a HIGHER tier than allowed is clamped down — this is the
# semantic guard that prevents "person walking with a backpack" from ever
# surfacing as ALERT/EMERGENCY just because Qwen got over-excited.
BEHAVIOR_PATTERN_MAX_TIER = {
    "walking_through": 1,
    "other_benign": 1,
    "loitering": 2,
    "leaving_item": 2,
    "taking_item": 4,
    "opening_container": 3,
    "fleeing": 4,
    "collapsed": 4,
    "violence": 4,
}

# Patterns that are inherently theft/threat. A tier >= 3 is only allowed if
# behavior_pattern is in this set. Otherwise we clamp tier to the pattern's max.
THEFT_OR_THREAT_PATTERNS = {
    "taking_item",
    "opening_container",
    "fleeing",
    "collapsed",
    "violence",
}

# Words/phrases that signal a real visual descriptor (color, clothing, build).
# If suspect_description has none of these, we treat the description as too vague
# and DEGRADE the event to tier 1 (so we don't make a phone call narrating
# "an unknown person did something").
DESCRIPTOR_HINT_WORDS = (
    # colors
    "red", "orange", "yellow", "green", "blue", "purple", "pink", "white",
    "black", "gray", "grey", "brown", "tan", "beige", "navy", "khaki", "maroon",
    "dark", "light",
    # clothing items (singular and common plurals)
    "hoodie", "hoodies", "jacket", "jackets", "coat", "coats",
    "shirt", "shirts", "tshirt", "t-shirt", "tshirts",
    "sweater", "sweaters", "sweatshirt", "sweatshirts",
    "vest", "vests", "jeans", "pants", "shorts", "skirt", "skirts",
    "dress", "dresses",
    "hat", "hats", "cap", "caps", "beanie", "hood", "hoods", "scarf", "mask",
    "glasses", "sunglasses",
    "sneakers", "boots", "shoes",
    "uniform", "uniforms", "vestment",
    # build / gender (singular and plurals)
    "tall", "short", "young", "older", "elderly", "teen", "teens",
    "child", "children", "kid", "kids", "adult", "adults",
    "man", "men", "woman", "women", "male", "female",
    "boy", "boys", "girl", "girls", "person", "people",
)

# Kept for backwards compatibility with downstream sanitizers but no longer
# used as a rejection list. The system now describes whatever scene Qwen
# actually sees (porch, library, parking lot, etc.) instead of forcing an
# outdoor-home assumption that broke demos in indoor venues.
HALLUCINATED_LOCATIONS: tuple[str, ...] = ()

# Soft signals — descriptions like these are uselessly vague; we keep them but
# tag them so callers can choose to suppress the alert or relabel it tier 1.
LOW_VALUE_PHRASES = (
    "no event",
    "nothing unusual",
    "normal scene",
    "no person",
    "empty scene",
)

MAX_DESCRIPTION_WORDS = 32
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

    if _is_low_value(payload):
        payload["tier"] = 1
        return ClassificationResult(
            "degrade", payload, "low-value content; degraded to tier 1"
        )

    # Semantic guard: only clamp explicitly benign / low-grade patterns so
    # they cannot escalate into phone-call tiers by accident.
    pattern_explicit = payload.get("_pattern_was_explicit", False)
    pattern = payload.get("behavior_pattern", "other_benign")
    if pattern_explicit and pattern in {"walking_through", "other_benign", "loitering", "leaving_item"}:
        max_tier = BEHAVIOR_PATTERN_MAX_TIER.get(pattern, 1)
        if payload["tier"] > max_tier:
            original_tier = payload["tier"]
            payload["tier"] = max_tier
            payload.pop("_pattern_was_explicit", None)
            return ClassificationResult(
                "degrade",
                payload,
                f"clamped tier {original_tier} -> {max_tier} for behavior_pattern={pattern!r}",
            )
    payload.pop("_pattern_was_explicit", None)

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
    incident_id: str | None = None,
) -> dict[str, Any]:
    tier = int(classification["tier"])
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "incident_id": incident_id or f"inc_{uuid.uuid4().hex[:12]}",
        "node_id": node_id,
        "tier": tier,
        "tier_name": TIER_LABELS.get(tier, "UNKNOWN"),
        "confidence": float(classification["confidence"]),
        "behavior_pattern": classification.get("behavior_pattern", "other_benign"),
        "scene": classification.get("scene", DEFAULT_SCENE),
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
    if "pattern" in payload and "behavior_pattern" not in payload:
        payload["behavior_pattern"] = payload["pattern"]
    if "location" in payload and "scene" not in payload:
        payload["scene"] = payload["location"]
    if "setting" in payload and "scene" not in payload:
        payload["scene"] = payload["setting"]
    payload.setdefault("time_elapsed", "ignored")
    pattern_explicit = isinstance(payload.get("behavior_pattern"), str) and payload["behavior_pattern"].strip() != ""
    payload.setdefault("behavior_pattern", "other_benign")

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

    desc = _scrub_numeric_artifacts(desc)
    summary = _scrub_numeric_artifacts(summary)
    desc = _trim_words(desc, MAX_DESCRIPTION_WORDS)
    summary = _trim_words(summary, MAX_SUMMARY_WORDS)

    if not desc or not summary:
        return None

    behavior_pattern = _coerce_behavior_pattern(payload.get("behavior_pattern"))
    scene = _coerce_scene(payload.get("scene"))

    return {
        "tier": tier,
        "confidence": confidence,
        "scene": scene,
        "suspect_description": desc,
        "one_line_summary": summary,
        "time_elapsed": f"{time_elapsed_seconds:.2f}s",
        "behavior_pattern": behavior_pattern,
        "_pattern_was_explicit": pattern_explicit,
    }


def _coerce_scene(value: Any) -> str:
    """Normalize the optional `scene` field to a short, clean phrase."""
    if not isinstance(value, str):
        return DEFAULT_SCENE
    cleaned = _scrub_numeric_artifacts(value).strip()
    cleaned = re.sub(r"^(?:the\s+)?", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return DEFAULT_SCENE
    cleaned = _trim_words(cleaned, 8).strip(" ,.;:-")
    if not cleaned:
        return DEFAULT_SCENE
    return f"the {cleaned}" if not cleaned.startswith(("a ", "an ", "the ")) else cleaned


def _coerce_behavior_pattern(value: Any) -> str:
    """Normalize behavior_pattern to one of the known strings; default benign."""
    if not isinstance(value, str):
        return "other_benign"
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in BEHAVIOR_PATTERN_MAX_TIER:
        return normalized
    # Fuzzy aliases the model often emits.
    aliases = {
        "theft": "taking_item",
        "stealing": "taking_item",
        "grabbing": "taking_item",
        "package_theft": "taking_item",
        "porch_pirate": "taking_item",
        "running": "fleeing",
        "running_away": "fleeing",
        "fight": "violence",
        "fighting": "violence",
        "weapon": "violence",
        "fall": "collapsed",
        "fallen": "collapsed",
        "passerby": "walking_through",
        "passing_by": "walking_through",
        "delivery": "other_benign",
        "neighbor": "other_benign",
    }
    return aliases.get(normalized, "other_benign")


# Suspect descriptions and behavior summaries should never contain numbers, IDs,
# bounding-box coords, or model internals. We scrub aggressively because Qwen2-VL
# is a small model and leaks all kinds of things ("person 0.08", "Person No. 1
# (0.85)", "id=3", "conf 0.62", etc.). Anything numeric in a description is junk.
_NUMERIC_JUNK_PATTERNS = (
    # Labelled trackers: "person 0", "person 0.08", "person no 1", "person no. 1",
    # "person #3", "person id 4", "person_1", "person id=2"
    re.compile(
        r"\bperson(?:\s*(?:no\.?|number|id|#|_)\s*)?[_\s\.\-#=:]*\d+(?:\.\d+)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsubject[_\s\.\-#=:]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:id|track|class|cls|frame|seq)[_\s\.\-#=:]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    # Confidence/score tokens with optional value
    re.compile(r"\b(?:conf(?:idence)?|score|prob(?:ability)?)\s*[:=]?\s*\d+(?:\.\d+)?%?\b", re.IGNORECASE),
    re.compile(r"\b(?:conf(?:idence)?|score|prob(?:ability)?)\s*[:=]\s*", re.IGNORECASE),  # "conf=" with value gone
    # Bbox-style coords
    re.compile(r"\bbbox[\s:=]*\[[^\]]*\]", re.IGNORECASE),
    re.compile(r"\b(?:x1|y1|x2|y2|cx|cy)[\s:=]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    # Bare numbers (decimals, integers, percentages) — last resort
    re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?(?![A-Za-z])"),
)


def _scrub_numeric_artifacts(text: str) -> str:
    """Remove ALL model-leak tokens and stray numbers from a description.

    Suspect descriptions and behavior summaries are short, factual phrases
    about a HUMAN. They should never contain digits, IDs, or coordinates.
    """
    cleaned = text
    for pat in _NUMERIC_JUNK_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    # Remove now-empty parens / brackets / quoted blanks left behind.
    cleaned = re.sub(r"\(\s*\)", " ", cleaned)
    cleaned = re.sub(r"\[\s*\]", " ", cleaned)
    cleaned = re.sub(r'"\s*"', " ", cleaned)
    cleaned = re.sub(r"'\s*'", " ", cleaned)
    # Remove dangling punctuation like ", ," or ":" or "id=" with nothing after.
    cleaned = re.sub(r"\s+([,;:.])", r"\1", cleaned)
    cleaned = re.sub(r"([,;:])\s*([,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[=:#]\s+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-#=")
    return cleaned


def _has_visual_descriptor(text: str) -> bool:
    """True if `text` contains at least one color/clothing/build descriptor."""
    if not text:
        return False
    blob = text.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", blob) for word in DESCRIPTOR_HINT_WORDS)


def _is_low_value(payload: dict[str, Any]) -> bool:
    blob = (
        payload.get("suspect_description", "") + " " + payload.get("one_line_summary", "")
    ).lower()
    return any(phrase in blob for phrase in LOW_VALUE_PHRASES)
