"""Action-router core. ``execute_action(event_json)`` is the single entry
point used by `action_router.service` (FastAPI ``POST /event``) and by the
vision pipeline when it wants to escalate.

WIRING THE THEFT DETECTOR
-------------------------
The theft tracker (``vision_pipeline/theft_tracker.py``) fires an event
whenever its state machine reaches ``THEFT_CONFIRMED``. To plug it in:

    import requests, os
    requests.post(
        os.environ["ACTION_ROUTER_URL"],            # e.g. http://127.0.0.1:8001/event
        json={
            "tier": 4,                              # 4 = EMERGENCY for confirmed theft
            "tier_name": "EMERGENCY",
            "event_id":     "evt_<uuid>",           # any unique string per attempt
            "incident_id":  "inc_<uuid>",           # stable per real-world incident;
                                                    # used to dedupe within 3 minutes
            "behavior_pattern":   "taking_item",    # tier-clamped via the table below
            "confidence":         0.92,             # in [0,1]; floors below downgrade
            "scene":              "the front porch",
            "suspect_description":"tall man in red hoodie and dark jeans",
            "one_line_summary":   "person took a package and walked away",
            "time_elapsed":       "just now",
            "yolo_classes":       ["person", "backpack"],
            "clip_path":          "./media/clip_inc_<id>.mp4",  # optional iMessage attachment
        },
        timeout=10,
    )

The router does the rest: idempotency, narration, Twilio fan-out, iMessage,
clip attachment, and a synchronous JSON receipt for logging.

TIER ESCALATION
---------------
    1 AMBIENT   - log only
    2 NOTICE    - text-only iMessage fan-out (no call). Optional Twilio SMS.
    3 ALERT     - parallel: Twilio voice call (homeowner) + Twilio SMS (homeowner
                  and family if FAMILY_PHONE) + iMessage fan-out w/ clip.
    4 EMERGENCY - three parallel voice calls (dispatch + homeowner + family)
                  + iMessage fan-out w/ clip, all in parallel via ThreadPoolExecutor

Voice = Claude-generated narration → ElevenLabs MP3 in MEDIA_DIR → Twilio
``<Play>`` of ``PUBLIC_BASE_URL/media/<file>.mp3``. Falls back to ``<Say>``
with Twilio's stock voice when ElevenLabs is unavailable or PUBLIC_BASE_URL
is not internet-reachable (e.g. localhost during local dev).

iMessage = AppleScript to Messages.app on this Mac (see ``imessage.py``).
Sequential per-recipient (Apple drops parallel sends), but the whole fan-out
is dispatched concurrently with the Twilio call thread so it doesn't add
latency. Recipients come from ``IMESSAGE_RECIPIENTS`` env (E.164, comma-sep).

CONFIDENCE FLOORS
-----------------
``ALERT_CONFIDENCE_FLOOR`` (default 0.35) and ``EMERGENCY_CONFIDENCE_FLOOR``
(default 0.55) downgrade the tier when the model's confidence is too low.
Calibrated for Qwen2-VL-2B; raise these for stricter prod deployments.

HARDENING
---------
- Idempotency: same ``incident_id`` (preferred) or ``event_id`` arriving
  twice within DEDUP_WINDOW_SECONDS is ignored. Defends against the vision
  pipeline emitting the same theft under new event IDs (e.g. multiple
  frames in the same incident).
- Defensive tier coercion: accepts int, float, "3", "ALERT" — vision can
  emit any of these without crashing the router.
- Behavior-pattern clamping: a ``walking_through`` event tagged tier 4 by
  upstream still runs as tier 1 (see BEHAVIOR_PATTERN_MAX_TIER). The vision
  pipeline always wins on ceiling-direction; the router only ever lowers.

TESTING WITHOUT THE VISION PIPELINE
-----------------------------------
- ``scripts/send_test_event.py``  - POST a synthetic event and exercise the
  full router: dedup, narration, ElevenLabs, Twilio, iMessage. The path
  the friend's theft detector will hit at runtime.
- ``scripts/test_concurrent_calls.py`` - bypasses the router entirely and
  fires raw Twilio calls. Useful for tuning the voice script before
  bothering with end-to-end vision.
- ``scripts/test_imessage.py`` - macOS Messages.app smoke test only.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ._trace import trace, trace_exception
from .config import CONFIG, Config
from .imessage import IMessageResult, send_imessage_fanout
from .messaging import SmsResult, send_sms
from .narration import generate_script
from .return_flow import ReturnFlowResult, maybe_initiate_return
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
    return_flow: Optional[ReturnFlowResult] = None

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
            "return_flow": self.return_flow.to_dict() if self.return_flow else None,
        }


def execute_action(event_json: Dict[str, Any], config: Optional[Config] = None) -> ActionResult:
    cfg = config or CONFIG
    started_at = time.monotonic()
    trace(
        "EVENT_IN",
        level="BEGIN",
        incident=event_json.get("incident_id"),
        event=event_json.get("event_id"),
        tier_raw=event_json.get("tier"),
        pattern=event_json.get("behavior_pattern"),
        confidence=event_json.get("confidence"),
        scene=event_json.get("scene"),
        suspect=event_json.get("suspect_description"),
        clip_path=event_json.get("clip_path"),
    )
    raw_tier = _coerce_tier(event_json.get("tier"))
    tier, behavior_note = _apply_behavior_ceiling(raw_tier, event_json)
    tier, downgrade_note = _apply_confidence_floor(tier, event_json, cfg)
    label = TIER_LABELS.get(tier, "UNKNOWN")
    result = ActionResult(tier=tier, tier_label=label)
    if behavior_note:
        result.actions.append(behavior_note)
    if downgrade_note:
        result.actions.append(downgrade_note)
    trace(
        "TIER",
        level="STEP",
        final=tier,
        label=label,
        raw=raw_tier,
        behavior_note=behavior_note,
        downgrade_note=downgrade_note,
    )
    trace(
        "CONFIG",
        level="INFO",
        dry_run=cfg.dry_run,
        use_elevenlabs=cfg.use_elevenlabs,
        elevenlabs_play_enabled=cfg.elevenlabs_play_enabled(),
        public_base_url=cfg.public_base_url,
        twilio_configured=bool(cfg.twilio_account_sid),
        imessage_enabled=cfg.imessage_enabled,
    )
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
        trace(
            "DEDUP_SKIP",
            level="WARN",
            incident=event_json.get("incident_id"),
            event=event_json.get("event_id"),
        )
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

    trace("HANDLER", level="STEP", tier=tier, name=label)
    if tier == 1:
        out = _tier_ambient(event_json, cfg, result)
        trace("DONE", level="OK", elapsed_s=round(time.monotonic() - started_at, 3),
              actions=out.actions, errors=out.errors)
        return out
    if tier == 2:
        out = _tier_notice(event_json, cfg, result)
        trace("DONE", level="OK", elapsed_s=round(time.monotonic() - started_at, 3),
              actions=out.actions, errors=out.errors)
        return out
    if tier == 3:
        _tier_alert(event_json, cfg, result)
        _maybe_run_return_flow(event_json, cfg, result)
        trace("DONE", level="OK", elapsed_s=round(time.monotonic() - started_at, 3),
              actions=result.actions, errors=result.errors,
              calls=len(result.calls), messages=len(result.messages))
        return result
    if tier == 4:
        _tier_emergency(event_json, cfg, result)
        _maybe_run_return_flow(event_json, cfg, result)
        trace("DONE", level="OK", elapsed_s=round(time.monotonic() - started_at, 3),
              actions=result.actions, errors=result.errors,
              calls=len(result.calls), messages=len(result.messages))
        return result

    result.errors.append(f"unknown tier: {tier}")
    trace("DONE", level="ERR", elapsed_s=round(time.monotonic() - started_at, 3),
          errors=result.errors)
    return result


# Behavior patterns where a stolen package is plausible. Prevents filing a
# return when the alert was, e.g., a person collapsed on the porch.
RETURNABLE_BEHAVIOR_PATTERNS = {"taking_item", "opening_container"}


def _maybe_run_return_flow(
    event: Dict[str, Any], cfg: Config, result: ActionResult
) -> None:
    if not cfg.return_flow_enabled:
        return
    pattern = str(event.get("behavior_pattern") or "").strip().lower()
    if pattern not in RETURNABLE_BEHAVIOR_PATTERNS:
        result.actions.append(f"return_flow_skipped_pattern:{pattern or 'none'}")
        return
    try:
        flow = maybe_initiate_return(event, config=cfg)
    except Exception as exc:
        log.exception("return_flow raised")
        result.errors.append(f"return_flow: {exc}")
        return
    result.return_flow = flow
    result.actions.extend(flow.actions)
    result.errors.extend(flow.errors)


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
    # Fan out via iMessage if configured (text-only at tier 2 — keep it snappy).
    _fanout_imessage(event, cfg, result, attach_clip=False, label="notice")
    return result


def _tier_alert(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    if not cfg.homeowner_phone:
        result.errors.append("HOMEOWNER_PHONE not configured")
        return result
    script = generate_script(event, cfg)
    result.script = script
    media_url = _try_synthesize(script, cfg, result, prefix="alert_")

    # Fire iMessage first — it delivers faster than the Twilio call rings, so
    # recipients see the clip + description before any phone goes off.
    _fanout_imessage(event, cfg, result, attach_clip=cfg.imessage_attach_clip, label="alert")

    # Twilio call (homeowner) + Twilio SMS (homeowner, family if FAMILY_PHONE)
    # in parallel so the homeowner has a written record even before the call
    # connects, and Android-only family contacts (no iMessage) still get text.
    sms_body = _format_alert_sms_body(event)
    sms_targets = [("homeowner", cfg.homeowner_phone)]
    if cfg.family_phone:
        sms_targets.append(("family", cfg.family_phone))

    tasks: List[tuple[str, str, str, Optional[str]]] = [
        ("call_homeowner", "call", cfg.homeowner_phone, None),
    ]
    for label, num in sms_targets:
        tasks.append((f"sms_{label}", "sms", num, None))

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {}
        for action_label, kind, to, _unused in tasks:
            if kind == "call":
                fut = pool.submit(_place_call_safe, to, script, media_url, cfg)
            else:
                fut = pool.submit(_send_sms_safe, to, sms_body, cfg)
            futures[fut] = (action_label, kind)
        for fut in as_completed(futures):
            action_label, kind = futures[fut]
            try:
                outcome = fut.result()
                if outcome is None:
                    continue
                if kind == "call":
                    result.calls.append(outcome)
                else:
                    result.messages.append(outcome)
                result.actions.append(action_label)
            except Exception as exc:
                log.exception("Tier 3 %s failed", action_label)
                result.errors.append(f"{action_label}: {exc}")
    return result


def _tier_emergency(event: Dict[str, Any], cfg: Config, result: ActionResult) -> ActionResult:
    trace("NARRATION_BEGIN", level="BEGIN", tier=4, source="claude" if cfg.use_claude else "static_template")
    script = generate_script(event, cfg)
    result.script = script
    trace("SCRIPT", level="OK", chars=len(script), preview=script[:160])
    media_url = _try_synthesize(script, cfg, result, prefix="emergency_")
    trace("MEDIA_URL", level="STEP", url=media_url, fallback_will_use_say=media_url is None)
    # Fan out iMessage in parallel with the calls. iMessage delivery is faster
    # than the call ringing so the team has the clip on their phones the moment
    # they pick up.
    _fanout_imessage(event, cfg, result, attach_clip=cfg.imessage_attach_clip, label="emergency")

    # Build the call list: known slots first, then any extra neighbor numbers
    # from NEIGHBOR_PHONES (deduped on the raw E.164 string). The dedup is
    # important: the .env intentionally repeats family/dispatch numbers in
    # NEIGHBOR_PHONES for legibility, and we don't want to dial the same line
    # twice in one incident.
    candidate_targets = [
        ("dispatch", cfg.emergency_dispatch_phone),
        ("homeowner", cfg.homeowner_phone),
        ("family", cfg.family_phone),
    ]
    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    for label, num in candidate_targets:
        if num and num not in seen:
            targets.append((label, num))
            seen.add(num)
    for idx, num in enumerate(cfg.neighbor_phones, start=1):
        if num and num not in seen:
            targets.append((f"neighbor{idx}", num))
            seen.add(num)

    if not targets:
        result.errors.append("no emergency contacts configured")
        trace("CALLS_BEGIN", level="ERR", reason="no contacts configured")
        return result

    trace(
        "CALLS_BEGIN",
        level="BEGIN",
        n=len(targets),
        targets=[f"{lbl}={num}" for lbl, num in targets],
        media_url=media_url,
    )
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {}
        for label, num in targets:
            trace("CALL_SUBMIT", level="STEP", to=num, label=label,
                  kind="play" if media_url else "say")
            futures[pool.submit(_place_call_safe, num, script, media_url, cfg)] = (label, num)
        for fut in as_completed(futures):
            label, num = futures[fut]
            try:
                call = fut.result()
                if call:
                    result.calls.append(call)
                    result.actions.append(f"call_{label}")
                    trace("CALL_OK", level="OK", to=num, label=label, sid=call.sid,
                          dry_run=call.dry_run)
                else:
                    trace("CALL_NONE", level="WARN", to=num, label=label,
                          reason="place_call_safe returned None")
            except Exception as exc:
                log.exception("Emergency call to %s failed", label)
                result.errors.append(f"call_{label}: {exc}")
                trace_exception("CALL_ERR", exc, to=num, label=label)
    trace("CALLS_DONE", level="OK", placed=len(result.calls), errors=len(result.errors))
    return result


# ---- helpers --------------------------------------------------------------


def _media_url_serves_file(media_url: str, timeout: float = 2.5) -> tuple[bool, str]:
    """HEAD-probe the exact media URL Twilio is about to fetch.

    A stale or wrong PUBLIC_BASE_URL is the #1 cause of "application error"
    on Twilio Play calls: the host may be alive (ngrok forwarding, /health
    returns JSON) but doesn't have OUR mp3 on disk — Twilio gets a 404
    HTML page, can't parse it as audio, and aborts with the stock error
    voice. Probing the specific file URL is the only way to catch this.

    Returns (is_serveable, reason). Reason is empty on success, else a
    short tag for the trace.
    """
    if not media_url or not media_url.lower().startswith(("http://", "https://")):
        return False, "invalid_url"
    low = media_url.lower()
    if "127.0.0.1" in low or "localhost" in low:
        return False, "localhost_unreachable_from_twilio"
    try:
        import requests
        r = requests.head(media_url, timeout=timeout, allow_redirects=True)
    except Exception as exc:
        return False, f"head_exc:{type(exc).__name__}"
    if r.status_code != 200:
        return False, f"head_status:{r.status_code}"
    ct = (r.headers.get("content-type") or "").lower()
    if not any(token in ct for token in ("audio", "mpeg", "mp3", "octet-stream")):
        return False, f"content_type:{ct or 'unknown'}"
    return True, ""


def _try_synthesize(
    script: str, cfg: Config, result: ActionResult, prefix: str = "alert_"
) -> Optional[str]:
    if not script:
        trace("TTS_SKIP", level="WARN", reason="empty script")
        return None
    if not cfg.elevenlabs_play_enabled():
        if cfg.use_elevenlabs:
            trace(
                "TTS_SKIP",
                level="WARN",
                reason="elevenlabs_play_enabled() returned False",
                use_elevenlabs=cfg.use_elevenlabs,
                has_key=bool(cfg.elevenlabs_api_key),
                public_base_url=cfg.public_base_url,
                hint="public_base_url must not be localhost / 127.0.0.1 — Twilio fetches the MP3 from it",
            )
            log.warning(
                "USE_ELEVENLABS=true but <Play> disabled: need ELEVENLABS_API_KEY and "
                "PUBLIC_BASE_URL reachable from the internet (not localhost). Using Twilio <Say>."
            )
        else:
            trace("TTS_SKIP", level="INFO", reason="use_elevenlabs=false; falling back to <Say>")
        return None
    trace("TTS_BEGIN", level="BEGIN", voice_id=cfg.elevenlabs_voice_id,
          model_id=cfg.elevenlabs_model_id, output_format=cfg.elevenlabs_output_format,
          script_chars=len(script))
    t0 = time.monotonic()
    try:
        path = synthesize_mp3(script, cfg)
        size = path.stat().st_size if path.exists() else 0
        url = cfg.media_url(path.name)
        trace("TTS_OK", level="OK", file=path.name, bytes=size,
              elapsed_s=round(time.monotonic() - t0, 3), media_url=url)
    except Exception as exc:
        log.warning("ElevenLabs synthesis failed; falling back to <Say>: %s", exc)
        result.errors.append(f"tts: {exc}")
        trace_exception("TTS_ERR", exc, elapsed_s=round(time.monotonic() - t0, 3))
        return None

    # Confirm the URL Twilio is about to fetch actually serves the mp3 we
    # just wrote. Skip the probe in dry_run (test fixtures use unreachable
    # hosts) — the dry_run code path doesn't actually call Twilio anyway.
    if cfg.dry_run:
        result.media_url = url
        return url
    probe_t0 = time.monotonic()
    serveable, reason = _media_url_serves_file(url)
    if not serveable:
        path.unlink(missing_ok=True)
        trace(
            "MEDIA_UNREACHABLE",
            level="ERR",
            media_url=url,
            reason=reason,
            elapsed_s=round(time.monotonic() - probe_t0, 3),
            hint=("Twilio would have hit this URL and gotten a non-audio response → "
                  "'application error'. Falling back to <Say>. To get ElevenLabs voice, "
                  "either run `ngrok http 8001` on this Mac and update PUBLIC_BASE_URL "
                  "in .env, or set USE_ELEVENLABS=false."),
        )
        result.errors.append(f"media_unreachable:{reason}")
        return None
    trace("MEDIA_OK", level="OK", media_url=url,
          elapsed_s=round(time.monotonic() - probe_t0, 3))
    result.media_url = url
    return url


def _format_alert_sms_body(event: Dict[str, Any]) -> str:
    summary = event.get("one_line_summary", "Possible theft at your home.")
    desc = event.get("suspect_description", "")
    elapsed = event.get("time_elapsed", "just now")
    if desc:
        return (
            f"SafeWatch ALERT: {summary} ({desc}) — {elapsed}. "
            "Active alert; we are calling you now."
        )
    return (
        f"SafeWatch ALERT: {summary} — {elapsed}. "
        "Active alert; we are calling you now."
    )


def _send_sms_safe(to: str, body: str, cfg: Config) -> Optional[SmsResult]:
    trace("SMS_SUBMIT", level="STEP", to=to, chars=len(body))
    t0 = time.monotonic()
    try:
        sms = send_sms(to, body, config=cfg)
        trace("SMS_OK", level="OK", to=to, sid=sms.sid, dry_run=sms.dry_run,
              elapsed_s=round(time.monotonic() - t0, 3))
        return sms
    except Exception as exc:
        log.exception("SMS to %s failed", to)
        trace_exception("SMS_ERR", exc, to=to,
                        elapsed_s=round(time.monotonic() - t0, 3))
        raise


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
    t0 = time.monotonic()
    if media_url:
        trace("TWILIO_CALL_BEGIN", level="BEGIN", to=to, mode="play",
              media_url=media_url, fallback_chars=len(script or ""))
        try:
            call = place_call_play(to, media_url, fallback_text=script, config=cfg)
            trace("TWILIO_CALL_OK", level="OK", to=to, sid=call.sid,
                  dry_run=call.dry_run, twiml_chars=len(call.twiml),
                  elapsed_s=round(time.monotonic() - t0, 3))
            return call
        except Exception as exc:
            trace_exception("TWILIO_CALL_ERR", exc, to=to, mode="play",
                            elapsed_s=round(time.monotonic() - t0, 3),
                            hint="If 'application error' rings: PUBLIC_BASE_URL likely not Twilio-reachable, "
                                 "or the MP3 isn't being served at that URL.")
            raise
    if script:
        trace("TWILIO_CALL_BEGIN", level="BEGIN", to=to, mode="say",
              script_chars=len(script))
        try:
            call = place_call_say(to, script, config=cfg)
            trace("TWILIO_CALL_OK", level="OK", to=to, sid=call.sid,
                  dry_run=call.dry_run, twiml_chars=len(call.twiml),
                  elapsed_s=round(time.monotonic() - t0, 3))
            return call
        except Exception as exc:
            trace_exception("TWILIO_CALL_ERR", exc, to=to, mode="say",
                            elapsed_s=round(time.monotonic() - t0, 3))
            raise
    trace("TWILIO_CALL_SKIP", level="WARN", to=to,
          reason="no media_url and no script")
    return None


def _format_imessage_body(event: Dict[str, Any]) -> str:
    """Compose a one-shot iMessage body. Short, scannable, severity-led.

    Keeps the message under 280 chars so it doesn't wrap awkwardly on the
    notification preview while still surfacing the description + scene.
    """
    tier = _coerce_tier(event.get("tier"))
    label = TIER_LABELS.get(tier, "ALERT")
    icon = {1: "•", 2: "•", 3: "🔴", 4: "🚨"}.get(tier, "•")
    summary = (event.get("one_line_summary") or "Activity at your home.").strip()
    desc = (event.get("suspect_description") or "").strip()
    scene = (event.get("scene") or "").strip()
    confidence = _safe_confidence(event.get("confidence"))

    parts = [f"{icon} ThirdEye · T{tier} {label}", summary]
    if scene and scene.lower() not in summary.lower():
        parts.append(f"on {scene}")
    if desc and desc.lower() not in summary.lower():
        parts.append(f"({desc})")
    parts.append(f"confidence {int(confidence * 100)}%")
    return "  ·  ".join(parts)


def _imessage_recipient_union(cfg: Config) -> list[str]:
    """Recipients = IMESSAGE_RECIPIENTS ∪ {homeowner} ∪ NEIGHBOR_PHONES, deduped.

    The demo .env intentionally splits phone slots three ways for clarity
    (homeowner / dispatch+family / neighbor mesh), but for iMessage we want
    everyone in the loop on one fan-out. Dedupe on the raw E.164 string so
    overlap between slots only buzzes once.
    """
    seen: set[str] = set()
    out: list[str] = []
    sources: list[str] = []
    sources.extend(cfg.imessage_recipients)
    if cfg.homeowner_phone:
        sources.append(cfg.homeowner_phone)
    sources.extend(cfg.neighbor_phones)
    for num in sources:
        n = (num or "").strip()
        if n and n not in seen:
            out.append(n)
            seen.add(n)
    return out


def _fanout_imessage(
    event: Dict[str, Any],
    cfg: Config,
    result: ActionResult,
    *,
    attach_clip: bool,
    label: str,
) -> None:
    """Send the same iMessage to every recipient in the union fan-out list.

    No-ops when iMessage is disabled or the union is empty. Errors on
    individual sends are logged but don't fail the action — calls remain
    the primary signal path; iMessage is a parallel best-effort channel.
    """
    if not cfg.imessage_enabled:
        trace("IMSG_SKIP", level="INFO", reason="IMESSAGE_ENABLED=false")
        return
    recipients = _imessage_recipient_union(cfg)
    if not recipients:
        trace("IMSG_SKIP", level="WARN", reason="union of phone slots is empty")
        log.info("iMessage enabled but no recipients across all phone slots — skipping")
        return

    body = _format_imessage_body(event)
    attachment = event.get("clip_path") if attach_clip else None
    if attachment:
        # vision_pipeline writes paths as './media/clip_inc_...mp4' relative to
        # CWD. Resolve so AppleScript gets an absolute path.
        from pathlib import Path as _Path
        resolved = _Path(attachment).expanduser().resolve()
        if not resolved.exists():
            trace("IMSG_ATTACH_MISSING", level="WARN",
                  given=str(attachment), resolved=str(resolved),
                  hint="text-only fan-out will still happen, but no image will attach")
        attachment = str(resolved)

    trace("IMSG_BEGIN", level="BEGIN", n=len(recipients), recipients=recipients,
          attachment=attachment, label=label, body_chars=len(body))

    if cfg.dry_run:
        trace("IMSG_DRYRUN", level="INFO", n=len(recipients), preview=body[:140])
        log.info(
            "[dry_run] would iMessage %d recipients (%s): %s%s",
            len(recipients),
            label,
            body,
            f" + {attachment}" if attachment else "",
        )
        result.actions.append(f"imessage_dry_run_{label}")
        return

    t0 = time.monotonic()
    msgs = send_imessage_fanout(recipients, body, attachment=attachment)
    elapsed = round(time.monotonic() - t0, 3)
    result.messages.extend(
        SmsResult(to=m.to, sid="imessage", body=body, dry_run=False)
        for m in msgs
        if m.sent
    )
    sent_count = sum(1 for m in msgs if m.sent)
    fail_count = len(msgs) - sent_count
    for m in msgs:
        if m.sent:
            trace("IMSG_OK", level="OK", to=m.to,
                  attachment_sent=m.attachment_sent,
                  attachment_error=m.error if m.error else None)
        else:
            trace("IMSG_ERR", level="ERR", to=m.to, error=m.error)
    trace("IMSG_DONE", level="OK" if fail_count == 0 else "WARN",
          sent=sent_count, failed=fail_count, total=len(msgs), elapsed_s=elapsed)
    if sent_count:
        result.actions.append(f"imessage_{sent_count}/{len(msgs)}")
    if fail_count:
        for m in msgs:
            if not m.sent:
                result.errors.append(f"imessage[{m.to}]: {m.error}")


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
