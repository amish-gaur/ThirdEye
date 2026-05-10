"""Active-incident cache.

The action_router hook publishes here on every tier-3+ event. Inbound voice
reads here to decide whether a homeowner who just dialed in has an active
incident — and routes them to the IVR (acknowledge/cancel) instead of the
generic conversational path.

Decoupled from the events store on purpose: phone-infra must not block on
lane/live-query landing. We carry just enough payload to drive the IVR.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..inbound_voice.internal import redis_client

log = logging.getLogger("voice_state.cache")

ACTIVE_INCIDENT_TTL_SECONDS = 5 * 60  # 5 minutes


def _k_active_payload(incident_id: str) -> str:
    return f"voice:active:incident:{incident_id}"


def _k_active_homeowner(homeowner_id: str) -> str:
    return f"voice:homeowner:{homeowner_id}:active"


def publish_active_incident(
    event_payload: dict[str, Any],
    action_result: dict[str, Any] | None = None,
    *,
    ttl_seconds: int = ACTIVE_INCIDENT_TTL_SECONDS,
    redis: Any | None = None,
) -> bool:
    """Publish an event as an active incident. Best-effort.

    Called from the action_router hook for tier 3+ events. Stores both:
    1. `voice:active:incident:{id}` — full payload (homeowner sees details on inbound)
    2. `voice:homeowner:{id}:active` — pointer (caller-ID -> active incident)

    Returns True on success, False on any error (we never raise).
    """
    incident_id = (event_payload.get("incident_id") or event_payload.get("event_id") or "").strip()
    homeowner_id = (event_payload.get("homeowner_id") or "").strip()
    if not incident_id or not homeowner_id:
        log.debug("skipping active-incident publish: missing ids")
        return False
    try:
        r = redis if redis is not None else redis_client.get_redis()
        body = {
            "incident_id": incident_id,
            "homeowner_id": homeowner_id,
            "tier": event_payload.get("tier"),
            "tier_label": event_payload.get("tier_name") or event_payload.get("tier_label"),
            "summary": event_payload.get("one_line_summary") or "",
            "scene": event_payload.get("scene") or "",
            "behavior_pattern": event_payload.get("behavior_pattern") or "",
            "actions": (action_result or {}).get("actions", []),
        }
        pipe = r.pipeline()
        pipe.set(_k_active_payload(incident_id), json.dumps(body), ex=ttl_seconds)
        pipe.set(_k_active_homeowner(homeowner_id), incident_id, ex=ttl_seconds)
        pipe.execute()
        return True
    except Exception:
        log.exception("publish_active_incident failed (non-fatal)")
        return False


def get_active_incident_for_homeowner(
    homeowner_id: str, *, redis: Any | None = None
) -> dict[str, Any] | None:
    """Lookup used by the inbound webhook on caller-ID match."""
    try:
        r = redis if redis is not None else redis_client.get_redis()
        incident_id = r.get(_k_active_homeowner(homeowner_id))
        if not incident_id:
            return None
        body = r.get(_k_active_payload(incident_id))
        if not body:
            return None
        return json.loads(body)
    except Exception:
        log.exception("get_active_incident_for_homeowner failed (non-fatal)")
        return None


def clear_active_incident(
    incident_id: str, homeowner_id: str, *, redis: Any | None = None
) -> None:
    """Called when an incident is acknowledged/cancelled — frees the homeowner
    from the active-incident state for inbound routing decisions."""
    try:
        r = redis if redis is not None else redis_client.get_redis()
        pipe = r.pipeline()
        pipe.delete(_k_active_payload(incident_id))
        pipe.delete(_k_active_homeowner(homeowner_id))
        pipe.execute()
    except Exception:
        log.exception("clear_active_incident failed (non-fatal)")
