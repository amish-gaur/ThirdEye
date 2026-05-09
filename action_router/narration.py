"""Step 3a: Claude turns the event JSON into a short spoken script."""

from __future__ import annotations

import logging
from typing import Any, Dict

from .config import CONFIG, Config

log = logging.getLogger("action_router.narration")

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}

SYSTEM_PROMPT = """You are SafeWatch, a calm, factual neighborhood security agent.
You will be given a JSON describing a detected event. Produce a SHORT spoken script
(20-40 words, one short paragraph, no list, no emoji, no markdown) that the homeowner
or emergency contact will hear over an automated phone call.

Rules:
- Lead with what happened, then what to do.
- Use the suspect description verbatim if provided. Do NOT add details you weren't given.
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


def static_template(event: Dict[str, Any]) -> str:
    """Used when Claude is unavailable / disabled."""
    tier = int(event.get("tier", 1))
    desc = event.get("suspect_description", "an unknown person")
    summary = event.get("one_line_summary", "an event was detected at your home")
    elapsed = event.get("time_elapsed", "just now")
    if tier == 4:
        return (
            f"This is your SafeWatch agent. {summary} {elapsed}. "
            "Emergency services have been requested. Stay on the line."
        )
    if tier == 3:
        return (
            f"This is your SafeWatch agent. {elapsed}, {desc} {summary}. "
            "I have sent the clip to your phone. "
            "Press 1 to notify your neighbors, or 2 to ignore."
        )
    if tier == 2:
        return (
            f"This is your SafeWatch agent. {summary} {elapsed}. "
            "No action is needed."
        )
    return ""


def generate_script(event: Dict[str, Any], config: Config | None = None) -> str:
    """Returns the spoken script. Falls back to the static template on any error."""
    cfg = config or CONFIG
    tier = int(event.get("tier", 1))
    if tier == 1:
        return ""
    if not cfg.use_claude or not cfg.anthropic_api_key:
        return static_template(event)

    try:
        import anthropic  # local import — keep startup snappy if Claude not used
    except ImportError:
        log.warning("anthropic SDK not installed; using static template")
        return static_template(event)

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    user_prompt = build_user_prompt(event)
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
                return text
        except Exception as exc:
            log.warning("Claude call failed (model=%s): %s", model, exc)
    log.warning("All Claude attempts failed; using static template")
    return static_template(event)
