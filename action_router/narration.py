"""Step 3a: Claude turns the event JSON into a short spoken script.

Person 2 hardening:
- Sanitize incoming description/summary BEFORE narrating so a stray hallucinated
  location (e.g. "library") never reaches Twilio audio.
- Clamp script length so Twilio <Say>/ElevenLabs synthesis stays cheap and on-spec.
- Always return a usable script for tiers 2/3/4; never raise.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from .config import CONFIG, Config

log = logging.getLogger("action_router.narration")

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

# Kept for backwards compatibility. Empty by design — the system now describes
# whatever scene Qwen actually sees instead of forcing an outdoor-home assumption.
HALLUCINATED_LOCATIONS: tuple[str, ...] = ()

DEFAULT_SCENE = "the camera view"

MAX_SCRIPT_CHARS = 480  # ~30s of speech; safe for Twilio <Say> and small MP3s.

SYSTEM_PROMPT = """You are ThirdEye, a calm, factual security agent.
You will be given a JSON describing a detected event. Produce a SHORT spoken script
(25-45 words, one short paragraph, no list, no emoji, no markdown) that the
homeowner or emergency contact will hear over an automated phone call.

Style:
- Open with "ThirdEye is watching." then say what happened.
- Use the SUSPECT DESCRIPTION verbatim — this is the only physical detail you may
  share. Do NOT invent clothing colors, ages, or features beyond what's given.
- Use the SCENE verbatim when describing where the event happened
  (e.g. "at the library entrance", "in the parking lot", "at the front porch").
  Do NOT make up a location if SCENE is "the camera view".
- Reference the BEHAVIOR_PATTERN naturally (e.g. "appears to be taking a package",
  "is loitering near the door", "is running away with an item"). Never
  speak the raw enum string.
- Do NOT mention numbers, IDs, confidence scores, model names, or coordinates.

Endings (REQUIRED, exact wording):
- Tier 4 EMERGENCY: end with "Emergency services have been requested. Stay on the line."
- Tier 3 ALERT:    end with "This is an active alert."
- Tier 2 NOTICE:   end with "No action is needed."
- Tier 1 AMBIENT:  return an empty string.
"""


def build_user_prompt(event: Dict[str, Any]) -> str:
    tier = event.get("tier")
    return (
        "Event JSON:\n"
        f"  tier: {tier} ({TIER_LABELS.get(tier, '?')})\n"
        f"  behavior_pattern: {event.get('behavior_pattern', 'other_benign')!r}\n"
        f"  scene: {event.get('scene', DEFAULT_SCENE)!r}\n"
        f"  suspect_description: {event.get('suspect_description', '')!r}\n"
        f"  one_line_summary: {event.get('one_line_summary', '')!r}\n"
        f"  time_elapsed: {event.get('time_elapsed', 'just now')!r}\n"
        "Write the spoken script now."
    )


# Numeric junk patterns the validator should have stripped already, but we
# defend in depth in case events arrive from anywhere else (manual SMS, tests,
# a teammate POSTing raw JSON). Mirrors vision_pipeline.events scrubber.
_NUMERIC_JUNK_PATTERNS = (
    re.compile(
        r"\bperson(?:\s*(?:no\.?|number|id|#|_)\s*)?[_\s\.\-#=:]*\d+(?:\.\d+)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bsubject[_\s\.\-#=:]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:id|track|class|cls|frame|seq)[_\s\.\-#=:]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:conf(?:idence)?|score|prob(?:ability)?)\s*[:=]?\s*\d+(?:\.\d+)?%?\b", re.IGNORECASE),
    re.compile(r"\b(?:conf(?:idence)?|score|prob(?:ability)?)\s*[:=]\s*", re.IGNORECASE),
    re.compile(r"\bbbox[\s:=]*\[[^\]]*\]", re.IGNORECASE),
    re.compile(r"\b(?:x1|y1|x2|y2|cx|cy)[\s:=]*\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?(?![A-Za-z])"),
)

GENERIC_DESCRIPTIONS = {
    "",
    "a person",
    "person",
    "an unknown person",
    "unknown person",
    "individual",
    "subject",
}

LOWER_BODY_TERMS = (
    "jeans",
    "pants",
    "shorts",
    "skirt",
    "leggings",
    "trousers",
    "shoes",
    "sneakers",
    "boots",
)

YOLO_LABEL_FRIENDLY = {
    "person": "person",
    "backpack": "backpack",
    "handbag": "handbag",
    "suitcase": "suitcase",
    "package": "package",
}


def sanitize_field(text: str) -> str:
    """Strip markdown + numeric junk; collapse whitespace.

    Scene/location words (library, office, parking lot, ...) are intentionally
    KEPT — Qwen reports the actual scene now and the call narrates it.
    """
    if not text:
        return ""
    cleaned = re.sub(r"[`*_#>]+", " ", text)
    for pat in _NUMERIC_JUNK_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    cleaned = re.sub(r"\(\s*\)", " ", cleaned)
    cleaned = re.sub(r"\[\s*\]", " ", cleaned)
    cleaned = re.sub(r'"\s*"', " ", cleaned)
    cleaned = re.sub(r"'\s*'", " ", cleaned)
    cleaned = re.sub(r"\s+([,;:.])", r"\1", cleaned)
    cleaned = re.sub(r"[=:#]\s+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-#=")
    return cleaned


def _enrich_from_yolo(event: Dict[str, Any]) -> str:
    """Build a generic-but-grounded description from YOLO labels.

    Used when the VLM's `suspect_description` came back empty or generic.
    Example: yolo_classes=['person','backpack'] -> 'a person carrying a backpack'.
    """
    raw_classes = event.get("yolo_classes") or []
    if not isinstance(raw_classes, (list, tuple, set)):
        return ""
    labels = [YOLO_LABEL_FRIENDLY.get(str(c).lower()) for c in raw_classes]
    labels = [l for l in labels if l]
    if not labels:
        return ""
    has_person = "person" in labels
    carryables = [l for l in labels if l != "person"]
    if has_person and carryables:
        carry_phrase = " and ".join(carryables) if len(carryables) <= 2 else ", ".join(carryables)
        return f"a person carrying a {carry_phrase}"
    if has_person:
        return "a person"
    return "a person near " + ", ".join(carryables)


def sanitize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of `event` with description/summary/scene sanitized."""
    safe = dict(event)
    desc = sanitize_field(event.get("suspect_description", ""))
    if desc.strip().lower() in GENERIC_DESCRIPTIONS:
        enriched = _enrich_from_yolo(event)
        desc = enriched or desc or "an unknown person"
    safe["suspect_description"] = desc or "an unknown person"
    safe["one_line_summary"] = (
        sanitize_field(event.get("one_line_summary", ""))
        or "an event was detected at the camera view"
    )
    safe["scene"] = _normalize_scene(event.get("scene"))
    return safe


def _normalize_scene(value: Any) -> str:
    """Trim/clean the scene string and ensure it starts with an article."""
    if not isinstance(value, str):
        return DEFAULT_SCENE
    cleaned = sanitize_field(value)
    if not cleaned:
        return DEFAULT_SCENE
    cleaned_lower = cleaned.lower()
    if cleaned_lower.startswith(("the ", "a ", "an ")):
        return cleaned
    return f"the {cleaned}"


def _coerce_tier(value: Any) -> int:
    """Tolerant tier coercion: int / float / numeric string / tier name -> 1..4."""
    if isinstance(value, bool):
        return 1
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
            return 1
    else:
        return 1
    return max(1, min(4, n))


def static_template(event: Dict[str, Any]) -> str:
    """Used when Claude is unavailable / disabled."""
    safe = sanitize_event(event)
    tier = _coerce_tier(safe.get("tier", 1))
    desc = _spoken_description(safe["suspect_description"])
    summary = _ensure_period(_capitalize(_normalize_phrase(safe["one_line_summary"])))
    pattern = safe.get("behavior_pattern", "other_benign")
    scene = safe.get("scene", DEFAULT_SCENE)
    action_phrase = _phrase_for_pattern(
        pattern, _normalize_phrase(safe["one_line_summary"]), scene
    )
    if tier == 4:
        return _clamp(
            f"ThirdEye is watching. At {scene}, {_capitalize(desc)} {action_phrase} "
            "Emergency services have been requested. Stay on the line."
        )
    if tier == 3:
        return _clamp(
            f"ThirdEye is watching. At {scene}, {_capitalize(desc)} {action_phrase} "
            "This is an active alert."
        )
    if tier == 2:
        return _clamp(
            f"ThirdEye update. {summary} "
            "No action is needed."
        )
    return ""


_NUMERIC_ELAPSED = re.compile(r"^\s*\d+(?:\.\d+)?\s*s\s*$", re.IGNORECASE)


def _humanize_elapsed(text: str) -> str:
    """Convert robot phrases like '1.25s' to a phone-friendly 'moments ago'."""
    if not text:
        return "just now"
    if _NUMERIC_ELAPSED.match(text):
        return "moments ago"
    return text


def _spoken_description(text: str) -> str:
    """Keep the spoken description grounded to the clearest visible details.

    Lower-body clothing is easy for the VLM to guess from partial frames, so
    we strip trailing "... and dark jeans/pants/..." clauses from phone audio.
    """
    normalized = _normalize_phrase(text)
    if not normalized:
        return "an unknown person"
    lowered = normalized.lower()
    for term in LOWER_BODY_TERMS:
        match = re.search(rf"\band\b[^.]*\b{re.escape(term)}\b.*$", lowered)
        if match:
            cutoff = match.start()
            candidate = normalized[:cutoff].strip(" ,.;:-")
            if candidate:
                return candidate
    return normalized


# Behavior phrasing without scene — the opening sentence already states where.
# Keeps the call from feeling repetitive ("at the library ... at the library").
_PATTERN_PHRASES = {
    "taking_item": "appears to be taking an item.",
    "opening_container": "appears to be opening a package or container.",
    "fleeing": "is running away with an item.",
    "loitering": "is loitering in the area.",
    "leaving_item": "left an unattended item.",
    "collapsed": "appears to have collapsed.",
    "violence": "is involved in a physical altercation.",
    "walking_through": "appears to be passing through.",
    "other_benign": "was seen in the area.",
}


def _phrase_for_pattern(pattern: str, summary: str, scene: str) -> str:
    """Return a polished sentence describing the action.

    The scene is already mentioned in the opening of the script, so we keep
    pattern phrases scene-free to avoid repetition.
    """
    canon = _PATTERN_PHRASES.get(pattern)
    if canon:
        return canon
    return _ensure_period(_capitalize(summary))


def _normalize_phrase(text: str) -> str:
    """Collapse whitespace + strip trailing punctuation so we can re-end cleanly."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().rstrip(",.;:- ")


def _capitalize(text: str) -> str:
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _ensure_period(text: str) -> str:
    if not text:
        return ""
    if text[-1] in ".!?":
        return text
    return text + "."


def generate_script(event: Dict[str, Any], config: Config | None = None) -> str:
    """Returns the spoken script. Falls back to the static template on any error."""
    cfg = config or CONFIG
    tier = _coerce_tier(event.get("tier", 1))
    if tier == 1:
        return ""
    safe_event = sanitize_event(event)
    safe_event["tier"] = tier
    if cfg.low_latency_narration and tier >= 3:
        return static_template(safe_event)
    if not cfg.use_claude or not cfg.anthropic_api_key:
        return static_template(safe_event)

    try:
        import anthropic  # local import — keep startup snappy if Claude not used
    except ImportError:
        log.warning("anthropic SDK not installed; using static template")
        return static_template(safe_event)

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    user_prompt = build_user_prompt(safe_event)
    for model in (cfg.anthropic_model, cfg.anthropic_fallback_model):
        if not model:
            continue
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                block.text
                for block in msg.content
                if getattr(block, "type", None) == "text"
            ).strip()
            if text:
                return _clamp(sanitize_field(text)) or static_template(safe_event)
        except Exception as exc:
            log.warning("Claude call failed (model=%s): %s", model, exc)
    log.warning("All Claude attempts failed; using static template")
    return static_template(safe_event)


def _clamp(text: str, limit: int = MAX_SCRIPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "."
