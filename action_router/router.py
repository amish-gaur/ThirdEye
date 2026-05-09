"""Step 2: The router core.

`execute_action(event_json)` is the single entry point. Tier-specific behavior:

    1 AMBIENT   - log only
    2 NOTICE    - send SMS to homeowner
    3 ALERT     - Claude→ElevenLabs→Twilio Play call to homeowner
    4 EMERGENCY - parallel Twilio Play calls to dispatch + homeowner + family
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .config import CONFIG, Config
from .messaging import SmsResult, send_sms
from .narration import generate_script
from .tts import synthesize_mp3
from .voice import CallResult, place_call_play, place_call_say

log = logging.getLogger("action_router.router")

TIER_LABELS = {1: "AMBIENT", 2: "NOTICE", 3: "ALERT", 4: "EMERGENCY"}


@dataclass
class ActionResult:
    tier: int
    tier_label: str
    actions: List[str] = field(default_factory=list)
    script: Optional[str] = None
    media_url: Optional[str] = None
    calls: List[CallResult] = field(default_factory=list)
    messages: List[SmsResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_label": self.tier_label,
            "actions": self.actions,
            "script": self.script,
            "media_url": self.media_url,
            "calls": [
                {"to": c.to, "sid": c.sid, "dry_run": c.dry_run} for c in self.calls
            ],
            "messages": [
                {"to": m.to, "sid": m.sid, "dry_run": m.dry_run} for m in self.messages
            ],
            "errors": self.errors,
        }


def execute_action(event_json: Dict[str, Any], config: Optional[Config] = None) -> ActionResult:
    cfg = config or CONFIG
    tier = _coerce_tier(event_json.get("tier"))
    label = TIER_LABELS.get(tier, "UNKNOWN")
    result = ActionResult(tier=tier, tier_label=label)
    log.info("execute_action tier=%d (%s) summary=%r", tier, label, event_json.get("one_line_summary"))

    if tier == 1:
        return _tier_ambient(event_json, cfg, result)
    if tier == 2:
        return _tier_notice(event_json, cfg, result)
    if tier == 3:
        return _tier_alert(event_json, cfg, result)
    if tier == 4:
        return _tier_emergency(event_json, cfg, result)

    result.errors.append(f"unknown tier: {tier}")
    return result


# ---- tier handlers --------------------------------------------------------


def _tier_ambient(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    result.actions.append("log_only")
    log.info("AMBIENT logged: %s", event.get("one_line_summary"))
    return result


def _tier_notice(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    body = _format_sms_body(event)
    result.script = body
    if not cfg.homeowner_phone:
        result.errors.append("HOMEOWNER_PHONE not configured")
        return result
    try:
        sms = send_sms(cfg.homeowner_phone, body, config=cfg)
        result.messages.append(sms)
        result.actions.append("sms_homeowner")
    except Exception as exc:
        log.exception("Tier 2 SMS failed")
        result.errors.append(f"sms: {exc}")
    return result


def _tier_alert(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    if not cfg.homeowner_phone:
        result.errors.append("HOMEOWNER_PHONE not configured")
        return result
    script = generate_script(event, cfg)
    result.script = script
    media_url = _try_synthesize(script, cfg, result, prefix="alert_")
    call = _call(cfg.homeowner_phone, script, media_url, cfg, result)
    if call:
        result.actions.append("call_homeowner")
    return result


def _tier_emergency(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    script = generate_script(event, cfg)
    result.script = script
    media_url = _try_synthesize(script, cfg, result, prefix="emergency_")

    targets = [
        ("dispatch", cfg.emergency_dispatch_phone),
        ("homeowner", cfg.homeowner_phone),
        ("family", cfg.family_phone),
    ]
    targets = [(label, num) for label, num in targets if num]
    if not targets:
        result.errors.append("no emergency contacts configured")
        return result

    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {
            pool.submit(_place_call_safe, num, script, media_url, cfg): label
            for label, num in targets
        }
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                call = fut.result()
                if call:
                    result.calls.append(call)
                    result.actions.append(f"call_{label}")
            except Exception as exc:
                log.exception("Emergency call to %s failed", label)
                result.errors.append(f"call_{label}: {exc}")
    return result


# ---- helpers --------------------------------------------------------------


def _try_synthesize(
    script: str, cfg: Config, result: ActionResult, prefix: str = "alert_"
) -> Optional[str]:
    if not script:
        return None
    if not cfg.elevenlabs_play_enabled():
        if cfg.use_elevenlabs:
            log.warning(
                "USE_ELEVENLABS=true but <Play> disabled: need ELEVENLABS_API_KEY and "
                "PUBLIC_BASE_URL reachable from the internet (not localhost). Using Twilio <Say>."
            )
        return None
    try:
        path = synthesize_mp3(script, cfg)
        url = cfg.media_url(path.name)
        result.media_url = url
        return url
    except Exception as exc:
        log.warning("ElevenLabs synthesis failed; falling back to <Say>: %s", exc)
        result.errors.append(f"tts: {exc}")
        return None


def _call(
    to: str, script: str, media_url: Optional[str], cfg: Config, result: ActionResult
) -> Optional[CallResult]:
    try:
        call = _place_call_safe(to, script, media_url, cfg)
        if call:
            result.calls.append(call)
        return call
    except Exception as exc:
        log.exception("Call to %s failed", to)
        result.errors.append(f"call: {exc}")
        return None


def _place_call_safe(
    to: str, script: str, media_url: Optional[str], cfg: Config
) -> Optional[CallResult]:
    if media_url:
        return place_call_play(to, media_url, fallback_text=script, config=cfg)
    if script:
        return place_call_say(to, script, config=cfg)
    return None


def _format_sms_body(event: Dict[str, Any]) -> str:
    summary = event.get("one_line_summary", "Activity at your home.")
    desc = event.get("suspect_description", "")
    elapsed = event.get("time_elapsed", "just now")
    if desc:
        return f"SafeWatch: {summary} ({desc}) — {elapsed}. No action needed."
    return f"SafeWatch: {summary} — {elapsed}. No action needed."


def _coerce_tier(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(4, n))
