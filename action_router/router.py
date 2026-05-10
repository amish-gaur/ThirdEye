"""Step 2: The router core.

`execute_action(event_json)` is the single entry point. Tier-specific behavior:

    1 AMBIENT   - log only
    2 NOTICE    - send SMS to homeowner
    3 ALERT     - Claude→ElevenLabs→Twilio Play call to homeowner
    4 EMERGENCY - parallel Twilio Play calls to dispatch + homeowner + family

Person 2 hardening:
- Idempotency: same `incident_id` (preferred) or `event_id` arriving twice
  within DEDUP_WINDOW_SECONDS is ignored. Defends against vision sending the
  same candidate twice under new event IDs.
- Defensive tier coercion: accepts int, float, "3", "ALERT".
"""

from __future__ import annotations

import logging
import threading
import time
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
TIER_NAME_TO_INT = {v: k for k, v in TIER_LABELS.items()}
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

DEDUP_WINDOW_SECONDS = 180.0
_recent_event_keys: Dict[str, float] = {}
_dedup_lock = threading.Lock()


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
    duplicate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_label": self.tier_label,
            "actions": self.actions,
            "script": self.script,
            "media_url": self.media_url,
            "duplicate": self.duplicate,
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
    raw_tier = _coerce_tier(event_json.get("tier"))
    tier, behavior_note = _apply_behavior_ceiling(raw_tier, event_json)
    tier, downgrade_note = _apply_confidence_floor(tier, event_json, cfg)
    label = TIER_LABELS.get(tier, "UNKNOWN")
    result = ActionResult(tier=tier, tier_label=label)
    if behavior_note:
        result.actions.append(behavior_note)
    if downgrade_note:
        result.actions.append(downgrade_note)
    log.info(
        "execute_action tier=%d (%s) raw_tier=%d event_id=%s incident_id=%s pattern=%s conf=%.2f summary=%r",
        tier,
        label,
        raw_tier,
        event_json.get("event_id"),
        event_json.get("incident_id"),
        event_json.get("behavior_pattern", "?"),
        _safe_confidence(event_json.get("confidence")),
        event_json.get("one_line_summary"),
    )

    if _is_duplicate(event_json):
        result.duplicate = True
        result.actions.append("dedup_skip")
        log.info(
            "Skipping duplicate event event_id=%s incident_id=%s",
            event_json.get("event_id"),
            event_json.get("incident_id"),
        )
        return result

    # Mutate the event in place so downstream narration sees the corrected tier.
    if tier != raw_tier:
        event_json = dict(event_json)
        event_json["tier"] = tier
        event_json["tier_name"] = label

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


def _safe_confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply_confidence_floor(
    tier: int, event_json: Dict[str, Any], cfg: Config
) -> tuple[int, Optional[str]]:
    """Downgrade tier when classifier confidence is below the configured floor.

    Tier 4 needs >= EMERGENCY_CONFIDENCE_FLOOR. Below that we step it down to 3.
    Tier 3 needs >= ALERT_CONFIDENCE_FLOOR. Below that we step it down to 2.
    Returns (final_tier, optional action-tag).
    """
    if tier < 3:
        return tier, None
    confidence = _safe_confidence(event_json.get("confidence"))
    new_tier = tier
    if tier == 4 and confidence < cfg.emergency_confidence_floor:
        new_tier = 3
    if new_tier == 3 and confidence < cfg.alert_confidence_floor:
        new_tier = 2
    if new_tier == tier:
        return tier, None
    note = f"downgrade_tier_{tier}_to_{new_tier}_low_confidence"
    log.warning(
        "Downgrading tier %d -> %d (confidence=%.2f, alert_floor=%.2f, emergency_floor=%.2f)",
        tier,
        new_tier,
        confidence,
        cfg.alert_confidence_floor,
        cfg.emergency_confidence_floor,
    )
    return new_tier, note


def _apply_behavior_ceiling(
    tier: int, event_json: Dict[str, Any]
) -> tuple[int, Optional[str]]:
    """Clamp only clearly non-call behaviors away from alert/emergency tiers."""
    pattern = str(event_json.get("behavior_pattern") or "").strip().lower()
    max_tier = BEHAVIOR_PATTERN_MAX_TIER.get(pattern)
    if pattern not in {"walking_through", "other_benign", "loitering", "leaving_item"}:
        return tier, None
    if max_tier is None or tier <= max_tier:
        return tier, None
    note = f"downgrade_tier_{tier}_to_{max_tier}_for_behavior_{pattern}"
    log.info(
        "Behavior ceiling downgrading tier %d -> %d for pattern=%s",
        tier,
        max_tier,
        pattern,
    )
    return max_tier, note


def _is_duplicate(event_json: Dict[str, Any]) -> bool:
    """True if the same incident/event key was seen within DEDUP_WINDOW_SECONDS."""
    dedup_key = _dedup_key(event_json)
    if not dedup_key:
        return False
    now = time.monotonic()
    with _dedup_lock:
        last_seen = _recent_event_keys.get(dedup_key)
        # Garbage-collect old entries opportunistically.
        stale = [k for k, v in _recent_event_keys.items() if now - v > DEDUP_WINDOW_SECONDS]
        for k in stale:
            _recent_event_keys.pop(k, None)
        _recent_event_keys[dedup_key] = now
        if last_seen is None:
            return False
        return (now - last_seen) <= DEDUP_WINDOW_SECONDS


def _dedup_key(event_json: Dict[str, Any]) -> str | None:
    incident_id = str(event_json.get("incident_id") or "").strip()
    if incident_id:
        return f"incident:{incident_id}"
    event_id = str(event_json.get("event_id") or "").strip()
    if event_id:
        return f"event:{event_id}"
    return None


def reset_dedup_cache() -> None:
    """Test-only helper: clear the in-memory dedup cache."""
    with _dedup_lock:
        _recent_event_keys.clear()


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
    to: str,
    script: str,
    media_url: Optional[str],
    cfg: Config,
    result: ActionResult,
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
    to: str,
    script: str,
    media_url: Optional[str],
    cfg: Config,
) -> Optional[CallResult]:
    if media_url:
        return place_call_play(
            to,
            media_url,
            fallback_text=script,
            config=cfg,
        )
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
    """Best-effort coercion: int / float / numeric string / tier name -> 1..4."""
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        n = int(value)
    elif isinstance(value, str):
        text = value.strip().upper()
        if text in TIER_NAME_TO_INT:
            return TIER_NAME_TO_INT[text]
        try:
            n = int(float(text))
        except ValueError:
            return 1
    else:
        return 1
    return max(1, min(4, n))
