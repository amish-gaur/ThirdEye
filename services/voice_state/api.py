"""FastAPI router for cross-lane voice-state coordination.

Mounted at `/voice/state` by the inbound_voice app factory. Rishab's
outbound code calls these endpoints; the mobile API also reads from here.

Auth: internal endpoints (leg register/cancel, winner) are protected by an
internal token (env: `VOICE_STATE_INTERNAL_TOKEN`). The mobile-facing GET
uses the homeowner JWT.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..inbound_voice.internal.auth import HomeownerPrincipal, verify_jwt
from . import store
from .models import (
    CallLeg,
    CancelLegResponse,
    IncidentState,
    LegState,
    RegisterLegRequest,
    UpdateLegRequest,
    WinnerRequest,
    WinnerResponse,
)

log = logging.getLogger("voice_state.api")

router = APIRouter(prefix="/voice/state", tags=["voice-state"])


def _require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("VOICE_STATE_INTERNAL_TOKEN", "").strip()
    if not expected:
        # Dev mode: no token configured, allow. Production must set this.
        return
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")


# ---- internal coordination (Rishab's outbound calls these) ----------------


@router.post("/legs", response_model=CallLeg, dependencies=[Depends(_require_internal)])
def register(req: RegisterLegRequest) -> CallLeg:
    """Register an active call leg under an incident.

    Idempotent on `call_sid`: re-registering refreshes timestamps but doesn't
    create a duplicate leg.
    """
    return store.register_leg(
        incident_id=req.incident_id,
        homeowner_id=req.homeowner_id,
        call_sid=req.call_sid,
        direction=req.direction,
        target_label=req.target_label,
        target_phone=req.target_phone,
    )


@router.patch(
    "/legs/{call_sid}",
    response_model=CallLeg | None,
    dependencies=[Depends(_require_internal)],
)
def update(call_sid: str, req: UpdateLegRequest) -> CallLeg | None:
    return store.update_leg_state(call_sid=call_sid, new_state=req.state)


@router.post(
    "/legs/{call_sid}/cancel",
    response_model=CancelLegResponse,
    dependencies=[Depends(_require_internal)],
)
def cancel(call_sid: str) -> CancelLegResponse:
    cancelled = store.cancel_leg(call_sid=call_sid)
    # The actual Twilio hangup is the caller's job (they have the SDK client).
    # We just record state.
    return CancelLegResponse(cancelled=cancelled, twilio_hangup_attempted=False)


@router.post(
    "/incidents/{incident_id}/winner",
    response_model=WinnerResponse,
    dependencies=[Depends(_require_internal)],
)
def declare_winner(incident_id: str, req: WinnerRequest) -> WinnerResponse:
    accepted, cancelled = store.declare_winner(incident_id=incident_id, call_sid=req.call_sid)
    return WinnerResponse(
        accepted=accepted,
        winner_call_sid=req.call_sid if accepted else (
            store.get_incident(incident_id=incident_id).winner_call_sid  # type: ignore[union-attr]
            if store.get_incident(incident_id=incident_id) else req.call_sid
        ),
        cancelled_legs=cancelled,
    )


# ---- mobile-facing read (homeowner JWT) -----------------------------------


@router.get("/incidents/{incident_id}", response_model=IncidentState)
def get_incident_state(
    incident_id: str,
    principal: HomeownerPrincipal = Depends(verify_jwt),
) -> IncidentState:
    state = store.get_incident(incident_id=incident_id)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
    if state.homeowner_id != principal.homeowner_id:
        # Don't leak existence — same code as not-found.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
    return state
