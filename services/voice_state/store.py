"""Redis-backed state machine.

Schema:
    voice:incident:{incident_id}        HASH    incident metadata
    voice:incident:{incident_id}:legs   SET     {call_sid}
    voice:incident:{incident_id}:winner STRING  call_sid (set once, atomic)
    voice:leg:{call_sid}                HASH    leg metadata + parent incident
    voice:homeowner:{homeowner_id}:active STRING incident_id (TTL'd)

Atomicity:
- "First-to-acknowledge wins" uses `SET NX` on the winner key. Whichever leg
  writes first locks the incident; subsequent attempts are no-ops.
- Leg state transitions are last-writer-wins. We never roll back a terminal
  state (completed/cancelled/failed) — those are sticky.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..inbound_voice.internal import redis_client
from .models import (
    CallDirection,
    CallLeg,
    IncidentState,
    IncidentVoiceState,
    LegState,
)

log = logging.getLogger("voice_state.store")

# How long an incident's state lives in Redis after the last update.
INCIDENT_TTL_SECONDS = 30 * 60  # 30 minutes
LEG_TTL_SECONDS = 60 * 60        # 1 hour (longer so Twilio status callbacks can land)
ACTIVE_HOMEOWNER_TTL_SECONDS = 5 * 60  # 5 minutes — used by inbound caller-ID routing

TERMINAL_LEG_STATES: frozenset[LegState] = frozenset(
    {LegState.COMPLETED, LegState.CANCELLED, LegState.NO_ANSWER, LegState.FAILED, LegState.BUSY}
)


# ---- keys -------------------------------------------------------------------


def _k_incident(incident_id: str) -> str:
    return f"voice:incident:{incident_id}"


def _k_legs(incident_id: str) -> str:
    return f"voice:incident:{incident_id}:legs"


def _k_winner(incident_id: str) -> str:
    return f"voice:incident:{incident_id}:winner"


def _k_leg(call_sid: str) -> str:
    return f"voice:leg:{call_sid}"


def _k_active_homeowner(homeowner_id: str) -> str:
    return f"voice:homeowner:{homeowner_id}:active"


# ---- writers ----------------------------------------------------------------


def register_leg(
    *,
    incident_id: str,
    homeowner_id: str,
    call_sid: str,
    direction: CallDirection,
    target_label: str,
    target_phone: str | None = None,
    redis: Any | None = None,
) -> CallLeg:
    """Add a leg under an incident. Idempotent: re-registering the same SID
    refreshes timestamps but doesn't duplicate."""
    r = redis if redis is not None else redis_client.get_redis()
    now_iso = _now_iso()

    pipe = r.pipeline()
    pipe.sadd(_k_legs(incident_id), call_sid)
    pipe.expire(_k_legs(incident_id), INCIDENT_TTL_SECONDS)

    leg_fields = {
        "call_sid": call_sid,
        "incident_id": incident_id,
        "homeowner_id": homeowner_id,
        "direction": direction.value,
        "target_label": target_label,
        "target_phone": target_phone or "",
        "state": LegState.RINGING.value,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    pipe.hset(_k_leg(call_sid), mapping=leg_fields)
    pipe.expire(_k_leg(call_sid), LEG_TTL_SECONDS)

    incident_fields = {
        "incident_id": incident_id,
        "homeowner_id": homeowner_id,
        "state": IncidentVoiceState.OPEN.value,
        "updated_at": now_iso,
    }
    # `created_at` only on first write (HSETNX-style emulation).
    pipe.hsetnx(_k_incident(incident_id), "created_at", now_iso)
    pipe.hset(_k_incident(incident_id), mapping=incident_fields)
    pipe.expire(_k_incident(incident_id), INCIDENT_TTL_SECONDS)

    pipe.execute()
    log.info(
        "registered leg call_sid=%s incident=%s homeowner=%s direction=%s target=%s",
        call_sid, incident_id, homeowner_id, direction.value, target_label,
    )
    return _read_leg(r, call_sid)


def update_leg_state(
    *,
    call_sid: str,
    new_state: LegState,
    redis: Any | None = None,
) -> CallLeg | None:
    """Move a leg through its lifecycle. Refuses to move out of a terminal
    state (completed/cancelled/failed/busy/no-answer)."""
    r = redis if redis is not None else redis_client.get_redis()
    current = r.hget(_k_leg(call_sid), "state")
    if current is None:
        return None
    if LegState(current) in TERMINAL_LEG_STATES:
        return _read_leg(r, call_sid)

    now_iso = _now_iso()
    pipe = r.pipeline()
    fields = {"state": new_state.value, "updated_at": now_iso}
    if new_state is LegState.ANSWERED:
        fields["answered_at"] = now_iso
    if new_state in TERMINAL_LEG_STATES:
        fields["ended_at"] = now_iso
    pipe.hset(_k_leg(call_sid), mapping=fields)
    pipe.expire(_k_leg(call_sid), LEG_TTL_SECONDS)
    pipe.execute()
    leg = _read_leg(r, call_sid)
    if leg:
        _maybe_resolve_incident(r, leg.incident_id)
    return leg


def declare_winner(
    *, incident_id: str, call_sid: str, redis: Any | None = None
) -> tuple[bool, list[str]]:
    """Atomic first-to-acknowledge. Returns (accepted, cancelled_call_sids).

    The first call to this for a given incident wins via `SET NX`. Subsequent
    callers see `accepted=False`. The winner's leg moves to ANSWERED; every
    other open leg moves to CANCELLED.
    """
    r = redis if redis is not None else redis_client.get_redis()
    set_ok = r.set(_k_winner(incident_id), call_sid, nx=True, ex=INCIDENT_TTL_SECONDS)
    if not set_ok:
        existing = r.get(_k_winner(incident_id))
        if existing == call_sid:
            return True, []  # idempotent re-claim
        return False, []

    now_iso = _now_iso()
    r.hset(_k_incident(incident_id), mapping={
        "state": IncidentVoiceState.ACKNOWLEDGED.value,
        "winner_call_sid": call_sid,
        "updated_at": now_iso,
    })
    r.hset(_k_leg(call_sid), mapping={
        "state": LegState.ANSWERED.value,
        "answered_at": now_iso,
        "updated_at": now_iso,
    })

    cancelled: list[str] = []
    for other_sid in r.smembers(_k_legs(incident_id)):
        if other_sid == call_sid:
            continue
        state = r.hget(_k_leg(other_sid), "state")
        if state and LegState(state) not in TERMINAL_LEG_STATES:
            r.hset(_k_leg(other_sid), mapping={
                "state": LegState.CANCELLED.value,
                "updated_at": now_iso,
                "ended_at": now_iso,
            })
            cancelled.append(other_sid)

    log.info(
        "declared winner incident=%s call_sid=%s cancelled=%d",
        incident_id, call_sid, len(cancelled),
    )
    return True, cancelled


def cancel_leg(*, call_sid: str, redis: Any | None = None) -> bool:
    """Cancel a single leg. Returns True if it transitioned, False if it was
    already terminal or unknown."""
    r = redis if redis is not None else redis_client.get_redis()
    current = r.hget(_k_leg(call_sid), "state")
    if current is None or LegState(current) in TERMINAL_LEG_STATES:
        return False
    now_iso = _now_iso()
    r.hset(_k_leg(call_sid), mapping={
        "state": LegState.CANCELLED.value,
        "updated_at": now_iso,
        "ended_at": now_iso,
    })
    leg = _read_leg(r, call_sid)
    if leg:
        _maybe_resolve_incident(r, leg.incident_id)
    return True


def cancel_incident(*, incident_id: str, redis: Any | None = None) -> int:
    """Hard-cancel every open leg for an incident. Returns count cancelled.
    Used when the homeowner explicitly tells us "false alarm, stop."""
    r = redis if redis is not None else redis_client.get_redis()
    n = 0
    for sid in r.smembers(_k_legs(incident_id)):
        if cancel_leg(call_sid=sid, redis=r):
            n += 1
    now_iso = _now_iso()
    r.hset(_k_incident(incident_id), mapping={
        "state": IncidentVoiceState.CANCELLED.value,
        "updated_at": now_iso,
    })
    return n


# ---- readers ----------------------------------------------------------------


def get_incident(*, incident_id: str, redis: Any | None = None) -> IncidentState | None:
    r = redis if redis is not None else redis_client.get_redis()
    fields = r.hgetall(_k_incident(incident_id))
    if not fields:
        return None
    legs_sids = list(r.smembers(_k_legs(incident_id)))
    legs = [leg for leg in (_read_leg(r, sid) for sid in legs_sids) if leg]
    return IncidentState(
        incident_id=fields.get("incident_id", incident_id),
        homeowner_id=fields.get("homeowner_id", ""),
        state=IncidentVoiceState(fields.get("state", IncidentVoiceState.OPEN.value)),
        winner_call_sid=fields.get("winner_call_sid") or None,
        legs=legs,
        created_at=_parse_iso(fields.get("created_at")),
        updated_at=_parse_iso(fields.get("updated_at")),
    )


def get_leg(*, call_sid: str, redis: Any | None = None) -> CallLeg | None:
    r = redis if redis is not None else redis_client.get_redis()
    return _read_leg(r, call_sid)


# ---- internals --------------------------------------------------------------


def _read_leg(r: Any, call_sid: str) -> CallLeg | None:
    fields = r.hgetall(_k_leg(call_sid))
    if not fields:
        return None
    return CallLeg(
        call_sid=fields["call_sid"],
        incident_id=fields["incident_id"],
        homeowner_id=fields["homeowner_id"],
        direction=CallDirection(fields["direction"]),
        target_label=fields["target_label"],
        target_phone=fields.get("target_phone") or None,
        state=LegState(fields["state"]),
        created_at=_parse_iso(fields["created_at"]),
        updated_at=_parse_iso(fields["updated_at"]),
        answered_at=_parse_iso(fields.get("answered_at")) if fields.get("answered_at") else None,
        ended_at=_parse_iso(fields.get("ended_at")) if fields.get("ended_at") else None,
    )


def _maybe_resolve_incident(r: Any, incident_id: str) -> None:
    """If every leg is terminal and there's no winner, mark incident RESOLVED."""
    sids = r.smembers(_k_legs(incident_id))
    if not sids:
        return
    if r.get(_k_winner(incident_id)):
        return
    states = {LegState(r.hget(_k_leg(s), "state")) for s in sids if r.hget(_k_leg(s), "state")}
    if states and states.issubset(TERMINAL_LEG_STATES):
        r.hset(_k_incident(incident_id), mapping={
            "state": IncidentVoiceState.RESOLVED.value,
            "updated_at": _now_iso(),
        })


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(s)
