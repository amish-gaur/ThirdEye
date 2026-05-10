# Lane: Phone infrastructure (branch `lane/phone-infra`)

> **You are on branch `lane/phone-infra`.** Build only what's described here. Three sibling branches (`lane/live-query`, `lane/mobile-ux`, `lane/connection-mesh`) are running in parallel — respect file boundaries below.
>
> Read `docs/PLAN_ADITYA.md` Lane 2 first. This file is the branch-scoped contract.

---

## Mission

Build inbound voice handling and the call-state machine. Production-grade Twilio inbound: caller-ID lookup, two-path IVR (active-incident vs conversational), recordings + transcripts, and a shared state machine that **both** inbound (yours) and outbound (Rishab's) write to so they never collide.

---

## Files this branch OWNS

- `services/inbound_voice/` — entire subtree (Twilio webhooks, IVR, status callbacks, recording handler)
- `services/voice_state/` — Redis-backed state machine + internal HTTP API for outbound coordination
- One surgical hook in `action_router/router.py` — see "Hook contract" below.
- New TwiML helper functions in `action_router/twiml.py` — only ADD functions, do not modify existing ones. Specifically: `connect_stream()` for `<Connect><Stream>` to Rishab's WS agent.
- `requirements.txt` — add: `redis`, `httpx` (if not already present)
- Tests under `tests/services/inbound_voice/` and `tests/services/voice_state/`

## Files this branch DOES NOT TOUCH

- `vision_pipeline/` — Amish.
- `services/query/`, `services/events_store/`, `services/pairing/`, `services/signaling/` — other lanes.
- `apps/`, `packages/`, `infra/`.
- `action_router/voice.py` — outbound code; Rishab also touches this. Coordinate via the state machine API instead of editing his code.
- Existing functions in `action_router/twiml.py` — only add new ones.

## Hook contract (the only edit to `action_router/router.py`)

Append to `execute_action()` just before the final return:

```python
try:
    from services.voice_state.cache import publish_active_incident
    if result.tier >= 3:
        publish_active_incident(event_json, result.to_dict(), ttl_seconds=300)
except Exception:
    log.exception("voice_state publish failed (non-fatal)")
```

Best-effort only. Action router must never fail because of us.

## Contracts this lane PUBLISHES

- **Twilio webhooks:**
  - `POST /inbound/voice` — Twilio's voice URL points here.
  - `POST /voice/status` — Twilio status callback.
  - `POST /voice/dtmf` — IVR digit handler.
  - `POST /voice/recording` — recording-complete webhook.
- **Internal API for outbound coordination (Rishab consumes):**
  - `POST /voice/leg/register` — `{incident_id, call_sid, direction, target}` → registers an active call leg.
  - `POST /voice/leg/cancel` — `{call_sid}` → cancels and triggers a Twilio call hangup.
  - `GET /voice/state/{incident_id}` → current state (open/acknowledged/cancelled/escalated, active legs, winner).
  - `POST /voice/incident/{id}/winner` — first-to-acknowledge wins; cancels other legs.
- **Mobile API:**
  - `GET /incidents/{id}/calls` → all calls (in + out) with recording URLs and transcripts.
- **Pydantic models** at `services/inbound_voice/models.py` and `services/voice_state/models.py`.
- **TS type export** at `services/inbound_voice/_generated/voice.ts` for `lane/mobile-ux`.

## Contracts this lane CONSUMES

- **Rishab's voice agent WS endpoint** for conversational handoff. Env: `RISHAB_AGENT_WS_URL`. **STUB:** if unset, fall back to a `<Say>` IVR that says "agent unavailable, please use the app." Do NOT block on Rishab.
- **Clerk JWT** for the mobile API endpoints. Use `services/_shared/auth.py` if `lane/live-query` lands first; otherwise stub a verifier inline and replace at merge.
- **R2 credentials** for recording storage. Same fallback as auth.
- **Events store** from `lane/live-query` for incident lookup. **Primary path:** read from your Redis active-incident cache (you populate it via the hook). **Fallback:** if a homeowner asks about something stale, return "no active incident" rather than reading the events store directly. This keeps you decoupled.

## Coordination with Rishab

- Rishab's outbound agent calls `POST /voice/leg/register` when it places a call. Your state machine tracks it.
- When the homeowner answers either inbound or outbound, the answering leg calls `POST /voice/incident/{id}/winner` — you cancel the rest.
- Rishab's ElevenLabs WS expects raw audio frames per Twilio Media Streams spec. The handoff TwiML is `<Connect><Stream url="wss://...">`. You ship `connect_stream()` helper; he ships the WS handler.

## Sequencing within this branch

1. Redis state-machine schema + module (`services/voice_state/`).
2. Action-router hook to populate active-incident cache.
3. `POST /inbound/voice` with caller-ID lookup + two-path TwiML (active-incident IVR vs hand-off stub).
4. `POST /voice/status` + leg registration.
5. Recording webhook + R2 upload + transcription (start with Twilio's transcription, swap to Whisper later if quality demands).
6. `connect_stream()` TwiML helper + cutover to Rishab's WS once `RISHAB_AGENT_WS_URL` is set.
7. Mobile API: `GET /incidents/{id}/calls`.
8. Internal coordination API for outbound: leg register/cancel, winner.
9. End-to-end test: simulated tier-3 event → outbound rings → simulated inbound from same homeowner → outbound legs cancelled.

## Definition of done

- Inbound webhook routes correctly within 1 ring.
- State machine survives Redis restart (persistence on, AOF).
- No outbound + inbound collision under load (test with 50 concurrent simulated incidents).
- Every call has recording + transcript reachable through the API.
- DTMF fallback works when speech recognition fails.
- TS types generated and committed.

## Merge checklist

- [ ] `action_router/router.py` diff is exactly the single hook block.
- [ ] `action_router/twiml.py` diff only adds new functions.
- [ ] No edits to `action_router/voice.py`.
- [ ] No edits to `vision_pipeline/`, `apps/`, `packages/`, `infra/`, or other `services/*` subtrees.
- [ ] `requirements.txt` only adds.
- [ ] CI green.
