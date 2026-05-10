"""Twilio inbound voice webhooks.

Three endpoints:
    POST /inbound/voice         — initial Twilio webhook (caller dials our number)
    POST /inbound/voice/dtmf    — IVR digit handler
    POST /inbound/voice/status  — Twilio call status callback

Routing for /inbound/voice:
1. Resolve caller-ID → homeowner (phones.lookup_homeowner). Unknown number
   gets a polite hangup.
2. Look up the active incident (voice_state.cache). Two paths:
   - Active incident → short jurisdiction-aware disclosure + IVR
     (1=acknowledge, 2=cancel, 3=escalate).
   - No active incident → status briefing + goodbye. (Conversational handoff
     to Rishab's WS agent lands later via RISHAB_AGENT_WS_URL.)
3. Register the inbound leg in voice_state so /winner can cancel us if an
   outbound leg already won.

Caller-ID privacy: we never expose the homeowner's phone in TwiML or
metadata — only on Twilio's outbound `to=` field, which is invisible to
other parties. Outbound legs always show TWILIO_FROM_NUMBER.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response

from ..voice_state import cache, store
from ..voice_state.models import CallDirection, LegState
from . import phones
from .config import CONFIG
from .jurisdictions import (
    disclosure_preamble,
    lookup_by_phone,
    short_disclosure_preamble,
)
from .twiml import say_hangup, say_response, say_then_gather

log = logging.getLogger("inbound_voice.webhook")

router = APIRouter(prefix="/inbound", tags=["inbound-voice"])

# Map from Twilio CallStatus values to our LegState. Twilio sends:
# initiated, ringing, in-progress, completed, busy, no-answer, failed, canceled
_TWILIO_STATUS_TO_LEG: dict[str, LegState] = {
    "ringing": LegState.RINGING,
    "in-progress": LegState.ANSWERED,
    "answered": LegState.ANSWERED,
    "completed": LegState.COMPLETED,
    "busy": LegState.BUSY,
    "no-answer": LegState.NO_ANSWER,
    "failed": LegState.FAILED,
    "canceled": LegState.CANCELLED,
}


@router.post("/voice")
async def receive_voice(request: Request) -> Response:
    form = await _parse_form(request)
    from_e164 = (form.get("From") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()
    log.info("inbound voice from=%s call_sid=%s", from_e164, call_sid)

    homeowner_id = phones.lookup_homeowner(from_e164)
    if not homeowner_id:
        return _xml(
            say_hangup(
                "Thanks for calling SafeWatch. This line is for verified homeowners. "
                "Please open the SafeWatch app to set up your account. Goodbye."
            )
        )

    juri = lookup_by_phone(from_e164)
    active = cache.get_active_incident_for_homeowner(homeowner_id)

    if active:
        return _xml(_active_incident_twiml(
            call_sid=call_sid,
            from_e164=from_e164,
            homeowner_id=homeowner_id,
            juri=juri,
            active=active,
        ))

    return _xml(_quiet_status_twiml(juri))


@router.post("/voice/dtmf")
async def receive_dtmf(request: Request) -> Response:
    form = await _parse_form(request)
    digits = (form.get("Digits") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()
    incident_id = request.query_params.get("incident_id", "").strip()

    log.info("inbound dtmf call_sid=%s incident=%s digits=%r", call_sid, incident_id, digits)

    if not incident_id:
        return _xml(say_hangup("Session expired. Please call again. Goodbye."))

    if digits == "1":
        accepted, cancelled = store.declare_winner(incident_id=incident_id, call_sid=call_sid)
        if accepted:
            incident = store.get_incident(incident_id=incident_id)
            if incident:
                cache.clear_active_incident(incident_id, incident.homeowner_id)
            msg = (
                "Acknowledged. SafeWatch will continue monitoring. "
                f"{len(cancelled)} other call leg{'s' if len(cancelled) != 1 else ''} cancelled. Goodbye."
            )
            return _xml(say_hangup(msg))
        return _xml(say_hangup(
            "Another contact already responded to this alert. SafeWatch is monitoring. Goodbye."
        ))

    if digits == "2":
        store.cancel_incident(incident_id=incident_id)
        incident = store.get_incident(incident_id=incident_id)
        if incident:
            cache.clear_active_incident(incident_id, incident.homeowner_id)
        return _xml(say_hangup(
            "Cancelled. No further action will be taken. SafeWatch will continue monitoring. Goodbye."
        ))

    if digits == "3":
        # Mark escalated; the outbound lane re-fans-out at higher tier.
        # We surface the signal via voice_state so Rishab's code can pick it up.
        store.update_leg_state(call_sid=call_sid, new_state=LegState.ANSWERED)
        return _xml(say_hangup(
            "Escalated to emergency. SafeWatch is contacting your emergency dispatch now. Goodbye."
        ))

    return _xml(say_hangup("No valid selection. Goodbye."))


@router.post("/voice/status")
async def receive_status(request: Request) -> Response:
    form = await _parse_form(request)
    call_sid = (form.get("CallSid") or "").strip()
    twilio_status = (form.get("CallStatus") or "").strip().lower()
    leg_state = _TWILIO_STATUS_TO_LEG.get(twilio_status)
    if call_sid and leg_state is not None:
        store.update_leg_state(call_sid=call_sid, new_state=leg_state)
    return Response(status_code=204)


# ---- internals --------------------------------------------------------------


def _active_incident_twiml(
    *,
    call_sid: str,
    from_e164: str,
    homeowner_id: str,
    juri,
    active: dict,
) -> str:
    """IVR for the active-incident path."""
    store.register_leg(
        incident_id=active["incident_id"],
        homeowner_id=homeowner_id,
        call_sid=call_sid,
        direction=CallDirection.INBOUND,
        target_label="inbound",
        target_phone=from_e164,
    )
    store.update_leg_state(call_sid=call_sid, new_state=LegState.ANSWERED)

    summary = active.get("summary") or "activity at your home"
    scene = active.get("scene") or ""
    where = f" at {scene}" if scene else ""
    action_url = (
        f"{CONFIG.public_base_url}/inbound/voice/dtmf?incident_id={active['incident_id']}"
    )
    prompt = (
        f"{short_disclosure_preamble(juri)} "
        f"You have an active alert{where}: {summary}. "
        "Press 1 to acknowledge. Press 2 to cancel. Press 3 to escalate to emergency dispatch."
    )
    return say_then_gather(prompt, action_url, num_digits=1)


def _quiet_status_twiml(juri) -> str:
    """No active incident — short briefing + goodbye."""
    return say_response(
        f"{short_disclosure_preamble(juri)} "
        "Your home is currently quiet. No active alerts in the last five minutes. "
        "Goodbye."
    )


def _xml(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


async def _parse_form(request: Request) -> dict[str, str]:
    """Twilio sends application/x-www-form-urlencoded. Parse robustly."""
    raw = (await request.body()).decode("utf-8", errors="ignore")
    parsed = parse_qs(raw, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in parsed.items()}
