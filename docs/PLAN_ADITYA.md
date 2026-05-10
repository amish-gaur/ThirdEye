# Aditya — Implementation Plan

Owner: Aditya. Scope: live querying, phone infra, mobile UX, webcam↔web↔mobile connection mesh.

Goal: production-grade end-to-end. No fixtures in the demo path, real auth, real persistence, beautiful on every surface a homeowner sees, works across devices and networks.

---

## Decisions baked in (push back if any are wrong)

| Area | Choice | Why |
|---|---|---|
| Mobile app | **Expo (React Native)** | "Any device" demands iOS + Android; native WebRTC quality; real push notifications; mature ecosystem; one codebase. |
| Web app | **Next.js (App Router)** | Server components for the query surface, deploys to Vercel, shares design system + types with mobile via a `packages/ui` workspace. |
| Backend | **Extend the existing FastAPI action router** | Don't fork the stack. Add new modules under `action_router/` and `services/` — the `/event` contract stays stable so Amish + Rishab don't break. |
| Database | **MongoDB Atlas + Atlas Vector Search** | Already named in `docs/DESIGN.md`. Vector + structured filter in one query. Free tier is enough for prod-grade demo. |
| Object storage | **Cloudflare R2** | S3-compatible, no egress fees, signed URLs for clip playback to mobile + Twilio MMS. |
| WebRTC | **LiveKit (self-host on Fly.io)** | Production SFU, simulcast, recording, mature RN + web + Python SDKs, handles TURN. Eliminates the worst-case "build your own SFU" path. |
| IP camera bridge | **go2rtc** | RTSP/ONVIF/HLS → WebRTC, single binary, runs on the laptop node. Lets a Ring/Wyze/generic IP cam join the same mesh as a phone-as-camera. |
| Auth | **Clerk** | Production-grade auth with first-class Expo + Next.js SDKs; saves 2 weeks vs rolling our own. JWT works directly with FastAPI middleware. |
| Push notifications | **Expo Push** | One API for APNs + FCM; tier-aware payload; background delivery on both platforms. |
| Observability | **Sentry + Logfire** | Sentry for client crashes (Expo + Next), Logfire for FastAPI traces. |

If you want to swap any of these (e.g. Supabase instead of Mongo+Clerk, or LiveKit Cloud instead of self-host), tell me and I'll rewrite the affected sections.

---

## Repo layout (after this plan lands)

```
third eye/
├── action_router/          # existing — keep stable
├── vision_pipeline/        # Amish's territory
├── services/               # NEW — backend services I own
│   ├── query/              # live querying API
│   ├── inbound_voice/      # Twilio inbound webhooks
│   ├── signaling/          # LiveKit token broker + node registry
│   ├── pairing/            # QR/code-based device pairing
│   └── events_store/       # Mongo schemas, event ingestion fan-out
├── apps/
│   ├── mobile/             # Expo React Native app
│   └── web/                # Next.js homeowner web app
├── packages/
│   ├── ui/                 # shared design system (RN + RNW)
│   └── api-types/          # shared TS types generated from Pydantic
└── infra/
    ├── livekit/            # docker-compose + Fly.io configs
    ├── go2rtc/             # IP cam bridge config
    └── coturn/             # only if we decide not to use LiveKit's TURN
```

---

## Lane 1: Live querying

### What it is
Two query modes through one chat-like interface:
- **Historical:** *"Show me anyone in a hooded jacket last night,"* *"What deliveries happened today?"*
- **Live:** *"What's on the front porch right now?"*, *"Is the side gate clear?"*

Multi-turn ("zoom in on the third one", "play that back at half speed", "was the same person here yesterday?"). Streams results with cited clips.

### Architecture

**Ingestion:** every event from `action_router/router.execute_action` writes to Mongo (`events` collection) plus emits a CLIP embedding for any attached clip. This is a small additive change — a hook at the end of `execute_action` that posts to the events store.

**Storage shape (`events` collection):**
```json
{
  "_id": "evt_...",
  "incident_id": "inc_...",
  "node_id": "node_amish",
  "homeowner_id": "user_...",        // NEW — multi-tenant
  "tier": 3, "tier_label": "ALERT",
  "behavior_pattern": "taking_item",
  "confidence": 0.62,
  "scene": "the front porch",
  "suspect_description": "tall man in a black hoodie...",
  "one_line_summary": "...",
  "timestamp": ISODate(...),
  "clip_url": "r2://...",             // signed URL minted on read
  "clip_embedding": [768 floats],     // CLIP ViT-L/14, indexed via Atlas Vector
  "frame_seq": 1234,
  "yolo_classes": ["person", "package"],
  "actions_taken": ["call_homeowner", "sms_homeowner"],
  "raw_classifier": "...",            // for debugging / future re-scoring
}
```

Atlas Vector index on `clip_embedding`; standard indices on `(homeowner_id, timestamp)`, `(homeowner_id, tier)`, `(homeowner_id, behavior_pattern)`.

**Query service (`services/query/`):**
- `POST /query` — body: `{ question, conversation_id?, scope: "history"|"live"|"auto" }`
- Translation step: Claude turns the NL question into a retrieval plan (`{ time_range, tier_filter, behavior_filter, text_query, semantic_query }`) — pure JSON output, low temperature, cached by question hash.
- Retrieval: structured filter on Mongo + vector search on `clip_embedding` (text query embedded with CLIP text encoder). Results re-ranked by Claude with the original question + top 20 hits.
- Response streams via SSE: tokens for the answer, `clip` events with thumbnail+timestamp+severity for each cited clip. Mobile app renders inline.
- For live scope: the service grabs the latest frame from the requested node via the signaling service, sends it to Qwen with the question, streams the answer.

**Conversation memory:** Mongo `query_sessions` collection keyed by `conversation_id`. Each turn appends `{role, content, retrieved_clip_ids}`. Used for follow-ups ("the third one").

### What "done" looks like
- p50 latency < 1.2s to first token, < 2.5s to first cited clip.
- Survives "did anyone come to the porch in the last hour", "show me anyone wearing red yesterday", "is the driveway clear right now", and follow-ups ("zoom in on that one").
- Auth-gated per homeowner — never returns another user's clips.
- Fully integrated into mobile app (chat surface) and web app.

### Sequencing
1. Mongo schema + ingestion hook (extend router to emit to events store).
2. CLIP embedding worker (separate process; subscribes to a queue, writes embeddings back).
3. `POST /query` endpoint with structured retrieval (no semantic yet) — works against tier/behavior/time filters.
4. Add semantic search (Atlas Vector).
5. Streaming + multi-turn.
6. Live scope (current-frame Qwen).
7. Mobile + web chat UI hookup (covered in Lane 3).

---

## Lane 2: Phone infrastructure

### What it is
The current router is **outbound only** — it dials homeowner/family/dispatch when events fire. Production needs **inbound**: the homeowner can dial the ThirdEye number to query, acknowledge an active alert, escalate, or get a status briefing.

### Architecture

**Inbound entry (`services/inbound_voice/`):**
- Twilio number's webhook → `POST /inbound/voice` on FastAPI.
- Caller-ID → look up homeowner; if unrecognized, polite "this line is for ThirdEye homeowners" hangup.
- Two paths:
  - **Active incident path:** if there's a live tier-3+ event for this homeowner in the last 5 min, jump to "Press 1 to acknowledge, 2 to cancel, 3 to escalate, 4 to talk to the agent."
  - **Conversational path:** otherwise hand off to Rishab's ElevenLabs conversational agent for free-form ("anyone come to the porch today?", "what's happening now?") — same query backend as Lane 1.

**Call-state machine (`services/inbound_voice/state.py`):**
A single source of truth for which calls are active per homeowner. Outbound (Rishab's) and inbound (mine) both register here. Prevents double-dial and lets us cancel outbound legs when the homeowner answers an inbound call about the same incident.

State table per `incident_id`:
```
incident → { open|acknowledged|cancelled|escalated, active_legs: [call_sid…], winner: call_sid? }
```
Backed by Redis (Upstash for managed) so it survives FastAPI restarts and works across Fly.io machines.

**Twilio integration:**
- Reuse the existing TwiML builders in `action_router/twiml.py` — extend with a `<Connect><Stream>` variant for the conversational handoff to ElevenLabs.
- Status callbacks: `POST /voice/status` updates the state machine on every Twilio call event (`initiated → ringing → answered → completed`).

**Recording + transcripts:**
- Every inbound call recorded to R2 (signed URL).
- Transcribed via Twilio's recording transcription or Whisper (Whisper is better quality, costs more — start with Twilio's, swap later if needed).
- Surfaced in mobile app under the matching incident.

### Coordination with Rishab
- Rishab owns the **outbound conversational agent** (ElevenLabs voice agent) and the **fan-out** call orchestration.
- I own the **inbound webhooks** and the **shared state machine** that both lanes write to.
- Contract: a single `voice_state` Redis key per incident, plus an internal HTTP API (`POST /voice/leg/register`, `POST /voice/leg/cancel`, `GET /voice/state/{incident_id}`).

### What "done" looks like
- Homeowner dials the ThirdEye number → routed to the right path within 1 ring.
- Outbound + inbound never collide on the same incident.
- Every call has an associated recording and transcript visible in the mobile app.
- IVR works on flaky cell networks (DTMF fallback if speech recognition fails).

### Sequencing
1. State machine + Redis schema.
2. `/inbound/voice` webhook + caller-ID lookup + two-path TwiML.
3. Status callback handler.
4. Recording + transcription pipeline.
5. Hand-off integration with Rishab's voice agent (`<Connect><Stream>` to his agent's WS endpoint).
6. Mobile surface for call history per incident.

---

## Lane 3: Mobile UI/UX

### What it is
The homeowner-facing surface. Mobile-first because that's where push lands and where the camera lives. Beautiful, opinionated, native-feeling.

### Stack
- **Expo SDK (latest)** — managed workflow, EAS Build for TestFlight + Play, OTA updates.
- **Expo Router** — file-based routing, native stacks, deep links.
- **NativeWind** (Tailwind for RN) + **react-native-reanimated** for motion.
- **Zustand** for client state, **TanStack Query** for server state.
- **Clerk Expo** for auth.
- **LiveKit React Native SDK** for live video.
- **Expo Notifications** for push.

### Surfaces

**1. Onboarding**
- Sign in (Clerk).
- Pair first node: "scan QR on your laptop" or "use this phone as a camera." Smooth — it should feel like setting up an Apple TV.
- Set primary contact + family + emergency-dispatch slots.

**2. Home dashboard (`/`)**
- Top: current activity card. If incident open → big severity tile, live video, action buttons (Acknowledge, Escalate, Cancel, Call Agent).
- Mid: live tiles for each camera (small WebRTC previews, lazy-loaded so we don't burn battery).
- Bottom: "Today" digest — counts by tier, top events, weather/wildfire risk if relevant.

**3. Timeline (`/timeline`)**
- Infinite scroll, grouped by day.
- Events grouped by `incident_id` so a single theft = one card, not five.
- Severity-color spine on the left edge of each row.
- Tap → event detail.

**4. Event detail (`/event/[id]`)**
- Hero: looped clip player (HLS).
- AI description, scene, behavior_pattern, confidence.
- Action row: Acknowledge / Ignore / Escalate / Refund / Share.
- Refund status (driven by Rishab's flow): "Refund filed at 2:14 PM • Pending Amazon review" with a tap-through to the Amazon refund detail.
- Call history for this incident (transcripts inline).
- "Show similar" — runs vector search on this event's embedding against history.

**5. Live (`/live/[node]`)**
- Full-screen WebRTC stream.
- Pinch-to-zoom (digital), tap-to-snapshot.
- Switch nodes via swipe or top tab.

**6. Query (`/ask`)**
- Chat-style. Mic for voice input (Whisper on-device or Apple Speech).
- Streaming answer with inline clip carousels.
- Pinned recent questions.

**7. Settings (`/settings`)**
- Cameras (rename, delete, view diagnostics).
- Contacts + escalation rules.
- Severity tuning (per zone if we get fancy).
- Refund integrations (Amazon credentials linked via Rishab's flow).
- Privacy / data export / sign out.

### Design system (`packages/ui`)
- Color: graphite background (#0B0D10), elevated surfaces (#16191E), severity accents — green (#3DDC84), amber (#FFB020), red (#FF4D4F). High contrast, accessible.
- Type: Inter for body, SF Pro Display equivalent for headings, JetBrains Mono for timestamps/IDs.
- Motion: spring transitions on severity tiles; subtle Lottie pulse on tier-3 active card; crossfade on clip transitions.
- Haptics: light on tap, success on acknowledge, warning on tier-2 push, heavy on tier-3/4 push.
- Components: `<SeverityTile>`, `<ClipPlayer>`, `<ChatBubble>`, `<NodeBadge>`, `<EventRow>`, `<ActionPill>`, etc. Built on `@shopify/restyle` for theming.

### Push notifications
- Per-tier templates with deep links.
- Tier 1 silent (no notification).
- Tier 2 standard banner + SMS preserved.
- Tier 3 critical alert (iOS Critical Alerts entitlement) + ringtone via push.
- Tier 4 same as 3 plus haptic burst.

### What "done" looks like
- Ships to TestFlight + Play internal track.
- Three real homeowners (us) use it as our daily security app for a week without touching the web app.
- Works offline for cached timeline, queues acknowledges for replay.
- 60fps everywhere, no jank on dashboard scroll.

### Sequencing
1. Monorepo setup (`apps/mobile`, `apps/web`, `packages/ui`, `packages/api-types`).
2. Design tokens + base components.
3. Auth + onboarding shell.
4. Home dashboard (read from events API, no live yet).
5. Timeline + event detail.
6. Live view (LiveKit SDK).
7. Query chat surface.
8. Pairing flow (after Lane 4 lands).
9. Push notifications wiring.
10. Polish + animations.

---

## Lane 4: Webcam ↔ web ↔ mobile connection mesh

### What it is
The architectural promise of the project: any device, no extra hardware. A phone, a laptop, an IP cam — all join the same homeowner's mesh and stream to the same viewers. Works across NAT, across networks, across device classes.

### Architecture

**Node types**
- **Camera node:** anything that produces video. Phone (native app), laptop with webcam, IP camera (RTSP, bridged via go2rtc).
- **Brain node:** a laptop running `vision_pipeline`. Subscribes to one or more camera streams, runs YOLO + Qwen, posts events to the action router.
- **Viewer node:** mobile app or web app pulling streams.

A single physical device can be multiple node types. A phone is typically a camera + viewer.

**Identity**
- Each node has an ed25519 keypair generated on first install, persisted in OS secure storage (Keychain / Android Keystore / OS keyring on laptop).
- Node registers with `services/pairing/` against the homeowner's account.
- Every event blob is signed by the originating node — already in DESIGN.md, formalize the wire format here.

**Pairing flow**
1. User opens mobile app, taps "Add a camera" or "Add a brain."
2. App calls `POST /pairing/begin` → server returns a short-lived 6-digit code + a deep-link QR.
3. On the new device:
   - Phone: app launches with code prefilled (deep link).
   - Laptop: run `python -m scripts.pair`, paste code.
   - IP cam: user enters camera RTSP URL into the brain's go2rtc config via the web UI.
4. New device hits `POST /pairing/complete` with the code + its public key.
5. Server validates, mints a node JWT (homeowner-scoped), returns it.
6. Node persists JWT + homeowner ID; subsequent connections authenticate via JWT.

**Signaling + media (LiveKit)**
- LiveKit room per camera node, named `node:{node_id}`.
- Camera nodes publish their video track to their room.
- Brain nodes + viewer nodes subscribe.
- LiveKit handles SDP/ICE, simulcast, TURN.
- Token broker (`services/signaling/`) mints LiveKit JWTs from our own JWTs — checks homeowner ACL, embeds room + permissions.

**Brain → camera coupling**
- The brain node config lists which `node:{id}` rooms to subscribe to.
- The brain runs LiveKit's Python SDK, decodes frames, hands them to `vision_pipeline`.
- This decouples the brain from the camera — they don't need to be on the same machine, the same network, or the same OS.

**IP camera bridge (go2rtc)**
- Runs on a brain node's machine.
- Pulls RTSP/ONVIF from the IP cam.
- Republishes as WebRTC into the LiveKit room for that node.
- One-line config per camera: `streams: { driveway_cam: rtsp://user:pass@192.168.1.42/stream }`.

**Phone-as-camera**
- Expo app uses `react-native-webrtc` directly to publish a track to the LiveKit room.
- Background mode: posture as a camera while app is foregrounded; iOS background audio entitlement to keep the connection alive briefly when backgrounded (we don't actually want phones recording when the app is closed for privacy reasons, so we surface a clear "go live" toggle).

**NAT / TURN**
- LiveKit ships with TURN built in. Self-host on Fly.io with a TURN port range exposed.
- For the laptop-to-laptop case where both are on the same Tailscale net (DESIGN.md), we can skip the relay entirely — LiveKit picks the direct path automatically.

### Network topology

```
[ phone-cam ]          [ ip-cam ] ── go2rtc ──┐
      │                                       │
      └─── publishes ───────────────► [ LiveKit SFU on Fly.io ] ◄── publishes ──┐
                                              ▲                                  │
                                              │                                  │
                                       subscribes                                │
                                              │                                  │
                                       [ brain (laptop) ]                  [ laptop-cam ]
                                              │
                                              │ posts events
                                              ▼
                                       [ FastAPI action router ] → Twilio / ElevenLabs / Mongo
                                              ▲
                                              │ live preview
                                              │
                                       [ mobile / web viewer ]
```

### What "done" looks like
- Pair a phone in < 30s end-to-end.
- p50 glass-to-glass latency on phone-cam → mobile-viewer < 400ms on the same Wi-Fi, < 800ms over LTE.
- An off-the-shelf IP cam (Wyze v3, Reolink) joins via go2rtc with one config line.
- Survives NAT on both sides (TURN relays when needed).
- Laptop brain can subscribe to streams from devices on different physical networks.
- All streams gated by homeowner JWT — no stream is publicly viewable.

### Sequencing
1. LiveKit deployed on Fly.io (TLS, TURN, persistent storage for recordings).
2. Token broker service (`services/signaling/`) — mints LiveKit JWTs from Clerk JWTs.
3. Pairing service (`services/pairing/`) + node registry collection in Mongo.
4. Phone-as-camera path in the Expo app.
5. Brain integration: Python LiveKit SDK pulls frames, feeds `vision_pipeline.engine`.
6. go2rtc config + adapter for IP cams.
7. Web viewer (Next.js + livekit-client).
8. Edge cases: stream restart on disconnect, simulcast tuning, recording retention policy.

---

## Cross-lane dependencies

| Depends on | Needed for |
|---|---|
| Mongo events schema (Lane 1) | Mobile timeline + event detail (Lane 3); inbound voice "active incident" lookup (Lane 2). |
| LiveKit deployed (Lane 4) | Live view in mobile (Lane 3); live-scope queries (Lane 1). |
| Clerk auth | Everything user-facing. Must land first. |
| Rishab's voice agent WS endpoint | Inbound conversational handoff (Lane 2). Define contract early. |
| Rishab's refund flow | Refund status surface in event detail (Lane 3). Mongo collection name + status enum to agree on. |
| Amish's `/event` payload shape | Stable already — just don't break it. |

---

## Suggested execution order (my critical path)

**Week 1** — foundations
- Monorepo + shared design tokens + api-types codegen.
- Clerk auth in FastAPI middleware + Expo + Next.
- Mongo schema + ingestion hook from action router.
- Deploy LiveKit on Fly.io.

**Week 2** — connection mesh
- Pairing service.
- Phone-as-camera in Expo.
- Brain LiveKit subscriber.
- go2rtc IP cam adapter.

**Week 3** — mobile shell
- Onboarding → Home dashboard → Timeline → Event detail.
- Push notifications.

**Week 4** — querying + live
- Query API (structured + semantic).
- Live scope (current-frame Qwen).
- Mobile + web chat surface.
- Live view in mobile (LiveKit SDK).

**Week 5** — phone infra + polish
- Inbound voice service + state machine.
- Coordination + handoff with Rishab's voice agent.
- Refund status surface.
- Polish, motion, haptics, perf.

**Week 6** — hardening
- Sentry + Logfire wired.
- Load test LiveKit, query latency.
- TestFlight + Play internal track.
- Security review (JWT scopes, R2 signed URLs, ACLs on every API).

---

## Open questions for you to resolve

1. **Are we building this on top of the current `main` branch directly, or do you want a `production` branch that diverges from the hackathon code?** I'd recommend `production` — keep `main` as the demo lineage.
2. **Domain + DNS — do you have one?** Affects Twilio webhook URLs, public LiveKit URL, deep-link configuration.
3. **Apple Developer + Google Play accounts ready?** Push notifications and TestFlight need them; ~2 weeks of approval lead time on Apple if not.
4. **Multi-tenant from day one or single-homeowner first?** The plan above assumes multi-tenant (Clerk + `homeowner_id` on every doc). It's slightly more work upfront but you can't bolt it on later cleanly.
