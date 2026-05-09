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

# Mirrors vision_pipeline.events.HALLUCINATED_LOCATIONS but local to action_router
# so the router has no hard dep on the vision package.
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

MAX_SCRIPT_CHARS = 480  # ~30s of speech; safe for Twilio <Say> and small MP3s.

SYSTEM_PROMPT = """You are SafeWatch, a calm, factual neighborhood security agent.
You will be given a JSON describing a detected event. Produce a SHORT spoken script
(20-40 words, one short paragraph, no list, no emoji, no markdown) that the homeowner
or emergency contact will hear over an automated phone call.

Rules:
- Lead with what happened, then what to do.
- Use the suspect description verbatim if provided. Do NOT add details you weren't given.
- Do NOT mention indoor places (library, classroom, office, kitchen, etc.); this is
  an outdoor home camera.
- Tier 3 ALERT: end with "Press 1 to notify your neighbors, or 2 to ignore."
- Tier 4 EMERGENCY: end with "Emergency services have been requested. Stay on the line."
- Tier 2 NOTICE: end with "No action is needed."
- Tier 1 AMBIENT: never narrated; if asked, return an empty string.
"""


def build_user_prompt(event: Dict[str, Any]) -> str:
    return (
        "Event JSON:\n"
        f"  tier: {event.get('tier')} ({TIER_LABELS.get(event.get('tier'), '?')})\n"
        f"  suspect_description: {event.get('suspect_description', '')!r}\n"
        f"  one_line_summary: {event.get('one_line_summary', '')!r}\n"
        f"  time_elapsed: {event.get('time_elapsed', 'just now')!r}\n"
        "Write the spoken script now."
    )


def sanitize_field(text: str) -> str:
    """Strip markdown, collapse whitespace, drop hallucinated location words."""
    if not text:
        return ""
    # Drop markdown emphasis / code ticks / brackets that creep in from VLMs.
    cleaned = re.sub(r"[`*_#>]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for word in HALLUCINATED_LOCATIONS:
        cleaned = re.sub(rf"\b{re.escape(word)}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    return cleaned


def sanitize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Return a shallow copy of `event` with description/summary sanitized."""
    safe = dict(event)
    safe["suspect_description"] = sanitize_field(event.get("suspect_description", "")) or "an unknown person"
    safe["one_line_summary"] = sanitize_field(event.get("one_line_summary", "")) or "an event was detected at your home"
    return safe


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
    desc = safe["suspect_description"]
    summary = safe["one_line_summary"]
    elapsed = safe.get("time_elapsed", "just now")
    if tier == 4:
        return _clamp(
            f"This is your SafeWatch agent. {summary} {elapsed}. "
            "Emergency services have been requested. Stay on the line."
        )
    if tier == 3:
        return _clamp(
            f"This is your SafeWatch agent. {elapsed}, {desc} {summary}. "
            "I have sent the clip to your phone. "
            "Press 1 to notify your neighbors, or 2 to ignore."
        )
    if tier == 2:
        return _clamp(
            f"This is your SafeWatch agent. {summary} {elapsed}. "
            "No action is needed."
        )
    return ""


def generate_script(event: Dict[str, Any], config: Config | None = None) -> str:
    """Returns the spoken script. Falls back to the static template on any error."""
    cfg = config or CONFIG
    tier = _coerce_tier(event.get("tier", 1))
    if tier == 1:
        return ""
    safe_event = sanitize_event(event)
    safe_event["tier"] = tier
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
