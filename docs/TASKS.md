# ThirdEye — Remaining Action Items

Owners: **Aditya, Amish, Rishab.**

Goal: production-grade end-to-end. Any webcam → laptop → phone → response, with mobile-first UI and bulletproof connection infra. No fixtures in the demo path, no rough edges on the surfaces a homeowner touches.

This doc is the **ownership contract**. Each owner expands their section into a deeper sub-plan when they pick up the work — keep it thin here.

---

## Aditya — phone infra, mobile UX

Branches: `lane/phone-infra`, `lane/mobile-ux`. See `docs/PLAN_LANE_PHONE.md` and `docs/PLAN_LANE_MOBILE.md` for branch-scoped plans.

### 1. Phone infrastructure
- Inbound call handling: homeowner dials the ThirdEye number to query / acknowledge / cancel an event.
- Stable Twilio webhook routing, call-state machine, retry + busy-line fallback.
- Coordinates with Rishab's outbound concurrent calling so inbound and outbound legs never collide.

### 2. Mobile UI/UX
Mobile-first homeowner app — opinionated, beautiful, not a desktop port.
- Live feed, event timeline grouped by severity tier, one-tap acknowledge / escalate / cancel.
- Refund status surface (driven by Rishab's Amazon flow).
- Push notifications tied to severity tier (silent for Tier 1, ring for Tier 2, cascade for Tier 3).

---

## Rishab — voice agents, concurrent calling, Amazon refunds, live querying, connection mesh

Branches: `lane/live-query`, `lane/connection-mesh` (plus voice/Amazon work to be branched separately). See `docs/PLAN_LANE_QUERY.md` and `docs/PLAN_LANE_MESH.md` for branch-scoped plans.

### 1. ElevenLabs conversational voice agent
- Replace static TTS on outbound calls with a real conversational agent (homeowner, family, "dispatch").
- Handles interruption, confirmation, escalation handoff back to the action router.

### 2. Concurrent calling
- Fan-out: simultaneously ring homeowner + family + emergency contact for Tier 3 events.
- First-to-acknowledge wins; remaining legs cancelled cleanly.
- Backed by a call-state machine — coordinates with Aditya's inbound handler via the shared state machine in `services/voice_state/`.

### 3. Amazon refund automation
~10% of stolen porch packages are Amazon. When ThirdEye detects a porch theft, we file the refund automatically — zero human input.
- Identify the matching order: Amazon API if accessible, otherwise authenticated browser automation against the user's account.
- Submit refund request bundled with: incident timestamp, video clip, AI-generated incident description.
- Rishab to expand this into a comprehensive sub-plan when he picks it up — the above is intentionally thin.

### 4. Live querying
Operator-facing natural-language queries over the live feed and event history.
- *"Anyone come to the porch in the last hour?"*, *"show me the driveway around 2pm"*, *"was there a delivery today?"*
- Backed by the vision pipeline event log + Qwen for visual grounding on stored frames.
- Returns ranked clips with timestamps, severity, and a one-line description.

### 5. Webcam ↔ web ↔ mobile connection mesh
The "any device, no extra hardware" promise — make it real. The simple way to connect any camera system regardless of internal infra.
- Pair-and-connect: scan a QR on the phone, phone becomes a camera node; laptop becomes a brain node; an IP webcam can join the same mesh.
- WebRTC for sub-second live feed to mobile, HLS fallback.
- Works across NAT (TURN), across networks, across device classes (iOS, Android, web).
- Per-node identity tied to the homeowner account; ed25519-signed event blobs as already specified in DESIGN.md.

---

## Amish — vision model

- Continue iterating the vision pipeline: accuracy, latency, false-positive rate.
- Multi-frame inference tuning, confidence-floor calibration, per-zone behavior tracking.
- Owns `vision_pipeline/` end-to-end; integration contract with the action router (`/event`) stays stable.

---

## Cross-cutting (everyone)

- Production-grade: real auth, real persistence, no hardcoded fixtures in the demo path.
- Beautiful mobile design carries through every surface a homeowner sees.
- Integration through the existing action router — keep the `/event` contract stable so the three workstreams don't block each other.
