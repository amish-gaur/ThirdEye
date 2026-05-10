# ThirdEye

**Turn any device with a camera into a full security system.**

A phone on a windowsill. A laptop on a desk. An old iPad in a drawer. ThirdEye turns hardware you already own into a porch-theft detection system that catches package thieves in the act, calls you, broadcasts to your neighbors, and *files the Amazon return for you* before you've even checked your phone.

No Ring. No subscription. No cloud surveillance. No $300 doorbell.

---

## The problem

**~104 million packages were stolen in the US last year.** 1 in 4 Americans has been a victim. Only 12% of reported thefts result in arrests. The total damage runs into the tens of billions.

The current options are bad:

- **Cloud cameras** (Ring, Nest, Wyze) work, but every frame goes to a corporation. Ring alone has 2,000+ police partnerships and an FTC settlement for employees viewing customers' bedrooms. Footage you paid to record can be handed over without a warrant. And you're paying $5–20/month for the privilege.
- **On-device privacy projects** (Frigate, Secluso) keep your footage at home, but they're isolated — a thief working five porches in a row is invisible to all five systems independently. The signal that matters in neighborhood crime is *between* houses, and they share nothing.
- **Every system flat-alerts.** Delivery person, stray cat, package thief — same ping. Real theft drowns in motion noise.

The hardware to solve this is already in everyone's pockets. Nobody has wired it up.

---

## What ThirdEye does

Point a phone or laptop camera at your porch. ThirdEye watches in real time and decides *how serious* what it sees is, then responds proportionally:

| Tier | What triggers it | What happens |
|---|---|---|
| **AMBIENT** | Routine activity — mailman dropping off, you walking past | Logged + indexed for search. No notification. |
| **NOTICE** | Stranger lingering near a package | Push notification with annotated frame |
| **ALERT** | Active package theft in progress | Twilio call + SMS with 8s clip and suspect description, signed broadcast to neighbors |
| **EMERGENCY** | Confirmed theft with the package gone | Parallel cascade: homeowner, family, full neighborhood mesh |

Then the part that makes it real: **after a confirmed theft, ThirdEye identifies the stolen package against your Amazon order history and files the return automatically.** A headless browser navigates Amazon's return flow, picks the right order, files the refund. Your stolen package becomes a refunded package before you've checked your phone.

That's the wedge. That's the working demo. Falls and wildfire smoke are the same architecture pointed at different prompts — interesting future work, not what you're seeing today.

---

## How it works

```
   ┌────────────────────────────────────────────────────────────────┐
   │  YOUR DEVICES (phone / laptop / iPad — anything with a camera) │
   └────────────────────────────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
      [ YOLOv11n ]       [ Face filter ]    [ Cross-cam ReID ]
       30 fps, ~9ms      excludes enrolled   stitches identity
       person + box      family members      across cameras
            │
            ▼  (only on trigger — saves compute)
      ┌──────────────────────────────────────┐
      │  Qwen2-VL (on-device VLM, int4)      │
      │  classifies into AMBIENT/NOTICE/     │
      │  ALERT/EMERGENCY + writes caption    │
      └──────────────────────────────────────┘
            │
            ▼  (signed event JSON, ~200 bytes — no frames leave)
      ┌──────────────────────────────────────┐
      │  ACTION ROUTER  (FastAPI, port 8001) │
      │  tier-aware dispatch + dedup         │
      └──────────────────────────────────────┘
            │
   ┌────────┼─────────┬──────────┬──────────┬───────────┐
   ▼        ▼         ▼          ▼          ▼           ▼
[Claude] [11Labs]  [Twilio]   [Mesh]    [Atlas]   [Auto-Return]
narrate   speak     call/SMS   peers    CLIP +    Playwright
                              (ed25519)  vector   files refund
                                         search   on Amazon
```

Five things make this work:

**1. Two-stage vision.** YOLOv11n is cheap (~9ms/frame) and runs constantly. It only triggers the heavier vision-language model when it sees a person near a package on the ground. This is the difference between burning a phone battery in two hours and running all day.

**2. On-device classification.** Severity is decided locally by Qwen2-VL running quantized on Apple Silicon. The corporation behind the model never sees your porch. Only the *result* — a tier label and a short text caption — leaves the device.

**3. Mesh, not cloud.** Devices peer over Tailscale. Each event is ed25519-signed before broadcast. Neighbors see *that* something happened, not *what it looked like*. A thief working five porches no longer looks like five disconnected events to five different cameras.

**4. Severity as a first-class primitive.** The action router is auditable Python — you can read every rule that decides whether your phone rings. Cloud competitors can't match this; their escalation logic is opaque corporate code.

**5. Closed-loop refund.** When an ALERT/EMERGENCY fires, a Qwen-powered package identifier matches the stolen item against your Amazon order history and a Playwright agent files the return. This is the first home-security system where the response is *recovery*, not just notification.

---

## The technical surface

- **Vision pipeline** — YOLOv11n + Qwen2-VL (int4 quantized) + InsightFace for family-member exclusion + TorchReID (OSNet) for cross-camera identity stitching. CoreML provider on Apple Silicon, MPS fallback. Throttled to 10 fps to avoid thermal runaway during long sessions.
- **Action router** — FastAPI service with a thread-pool dispatcher. Per-tier handlers compose Claude (narration) → ElevenLabs (TTS) → Twilio (voice/SMS) into parallel cascades. Dedup keys, replay protection, per-node rate limits.
- **Auto-return agent** — Qwen-based package identification against an indexed order-history snapshot, then a Playwright session with persisted auth state to drive Amazon's return flow end-to-end.
- **Provenance** — every event signed with ed25519. Clip hashes anchored in event metadata. Tamper-evident chain admissible as evidence.
- **Semantic recall** — every event gets a CLIP embedding stored in MongoDB Atlas Vector. Ask *"show me the guy in the red hoodie from Tuesday"* and get the clip back, in plain English.
- **Frontends** — React/Vite PWA (incident timeline, semantic search, node map, returns dashboard) and a native SwiftUI iOS app streaming over SSE.
- **Footage never leaves the home.** The one exception is the MMS clip the homeowner explicitly opted into receiving on ALERT/EMERGENCY tiers.

---

## Repository layout

```
vision_pipeline/    YOLO + Qwen2-VL + face filter + ReID + package ID
action_router/      FastAPI tier dispatcher (Claude / 11Labs / Twilio)
                    + Amazon auto-return agent (Playwright)
apps/figma-ui/      React PWA — timeline, search, returns dashboard
apps/ios/           Native SwiftUI app with SSE streaming
docs/               Design docs, architecture notes, demo checklist
```

Component docs live next to the code:
[`vision_pipeline/README.md`](vision_pipeline/README.md) ·
[`action_router/README.md`](action_router/README.md) ·
[`docs/DESIGN.md`](docs/DESIGN.md)

---

## Quick start

```bash
# 1. Install
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # add Anthropic, ElevenLabs, Twilio keys

# 2. Start the action router (port 8001)
python -m scripts.run_service

# 3. In another terminal, point a camera at the router
export ACTION_ROUTER_URL=http://127.0.0.1:8001/event
python -m scripts.run_vision

# 4. Smoke test the end-to-end cascade without a real camera
python -m scripts.send_test_event --tier 3
```

For the web UI:

```bash
cd apps/figma-ui && npm install && npm run dev   # http://localhost:5173
```

For the iOS app, open `apps/ios/ThirdEye.xcodeproj` in Xcode.

---

## Why this matters

The hardware needed to stop porch piracy has been sitting in drawers for a decade. The thing missing was the wiring — a way to share the *signal* without sharing the *footage*, a way to decide which events deserve a phone call versus a log line, and a way to *actually recover* what was stolen instead of just notifying you it's gone.

ThirdEye is that wiring. It runs on what you already own. It keeps your video at home. It treats severity as code you can read instead of a corporate black box. And when someone walks off with your package, it gets your money back automatically.

A phone, a laptop, and a router. That's the whole security system.
