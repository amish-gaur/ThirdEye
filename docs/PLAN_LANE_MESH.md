# Lane: Webcam ↔ web ↔ mobile mesh (branch `lane/connection-mesh`)

> **You are on branch `lane/connection-mesh`.** Build only what's described here. Three sibling branches (`lane/live-query`, `lane/phone-infra`, `lane/mobile-ux`) are running in parallel — respect file boundaries below.
>
> Read `docs/PLAN_ADITYA.md` Lane 4 first. This file is the branch-scoped contract.

---

## Mission

The "any device, no extra hardware" promise — made real. Phone-as-camera, laptop-as-brain, IP-cam-via-bridge, mobile-as-viewer. All on one homeowner mesh. Works across NAT, across networks, across device classes. Production-grade auth, sub-second latency.

This is the heaviest infra lane. LiveKit deploy, pairing service, IP cam bridge, brain integration.

---

## Files this branch OWNS

- **Backend services:**
  - `services/pairing/` — entire subtree (QR/code pairing, node registry, ed25519 verification)
  - `services/signaling/` — LiveKit JWT broker; ACL enforcement; `mint_view_token(node_id)` for live-query lane to consume
- **Infrastructure:**
  - `infra/livekit/` — docker-compose, Fly.io configs (`fly.toml`), TURN port range, TLS cert provisioning, ingress routing
  - `infra/go2rtc/` — config + adapter for IP cameras (RTSP/ONVIF → LiveKit)
  - `infra/livekit/EXPO_CONFIG.md` — **the doc** that `lane/mobile-ux` reads to add `react-native-webrtc` config plugin entries to their `app.json`. You write the doc, not the edit.
- **Brain integration (additive only — Amish's existing code untouched):**
  - `vision_pipeline/livekit_source.py` — NEW file. A `LiveKitFrameSource` class that subscribes to a LiveKit room and yields decoded frames in the same shape `engine.py` expects from a webcam. Amish opts in via env (`FRAME_SOURCE=livekit`) — you provide the source, he wires it in (or you wire it in via a small additive change in `engine.py` IF Amish OKs it; default: leave it for him to wire).
- `requirements.txt` — add: `livekit`, `livekit-api` (Python SDK + admin), `cryptography` (ed25519), `aiortc` (only if needed as a fallback)
- Tests under `tests/services/pairing/`, `tests/services/signaling/`, `tests/vision_pipeline/test_livekit_source.py`

## Files this branch DOES NOT TOUCH

- `vision_pipeline/engine.py` — Amish.
- `vision_pipeline/events.py`, `vision_pipeline/publisher.py` — Amish.
- `action_router/` — other lanes have hooks; you don't.
- `services/query/`, `services/events_store/`, `services/inbound_voice/`, `services/voice_state/` — other lanes.
- `apps/mobile/src/` — UI is `lane/mobile-ux`'s. **EXCEPTION:** you may write the EXPO_CONFIG doc, but you do NOT edit `apps/mobile/app.json` yourself.
- `apps/web/`, `packages/ui/`, `packages/livekit-client/` — these consume your contracts; mobile-ux owns them.

## Contracts this lane PUBLISHES

- **HTTP API:**
  - `POST /pairing/begin` → `{ code, qr_url, expires_at }` (auth: Clerk JWT for the homeowner who owns the new node)
  - `POST /pairing/complete` → `{ code, public_key, node_type, hint_name }` → `{ node_id, jwt }` (no auth — the code is the auth)
  - `POST /pairing/revoke` → `{ node_id }` (auth: Clerk JWT)
  - `GET /pairing/nodes` → list this homeowner's nodes
  - `POST /signaling/token` → `{ node_id, role: "publisher"|"subscriber" }` → LiveKit JWT
- **Python module:**
  - `services/signaling/livekit.py:mint_view_token(node_id, ttl_seconds=60)` → JWT string. Used by `lane/live-query` for live-scope queries. Stable signature.
- **Frame source:**
  - `vision_pipeline/livekit_source.py:LiveKitFrameSource` with the same iterator protocol as the existing webcam source so Amish can swap.
- **Naming convention:**
  - LiveKit room per node: `node:{node_id}`.
  - Camera publishes a track named `camera:main` (one per node v1; multi-camera-per-node deferred).
- **Pydantic models** at `services/pairing/models.py`, `services/signaling/models.py`.
- **TS type export** at `services/pairing/_generated/pairing.ts`, `services/signaling/_generated/signaling.ts` for `lane/mobile-ux`.

## Contracts this lane CONSUMES

- **Clerk JWT** verifier — use `services/_shared/auth.py` if `lane/live-query` lands first; else stub a verifier and replace at merge. Don't block on live-query.
- **Mongo** — collection `nodes`: `{ _id, homeowner_id, public_key, node_type, hint_name, created_at, last_seen, jwt_jti }`. Use `services/_shared/mongo.py` if available; else create your own thin client and reconcile at merge.

## EXPO_CONFIG doc structure (you write, mobile-ux reads)

`infra/livekit/EXPO_CONFIG.md` should contain, at minimum:
- Exact `app.json` plugin entries (`@livekit/react-native-expo-plugin`, `@config-plugins/react-native-webrtc`).
- Required iOS Info.plist entries (camera + mic permissions, microphone usage description, background modes if we keep camera alive briefly).
- Required Android `AndroidManifest.xml` permissions (CAMERA, RECORD_AUDIO, BLUETOOTH if we use BT for ranging in future).
- EAS Build profile additions.
- One-line `npx expo prebuild` instructions for verification.

Mobile-ux merges those into `app.json` when this lane lands.

## Brain wiring (the careful Amish coordination)

- v1 path: ship `livekit_source.py` standalone. Tell Amish via Slack/PR comment that it's ready. Provide an example: `engine.py` can detect `FRAME_SOURCE=livekit` and import `LiveKitFrameSource` instead of the webcam reader.
- Do NOT modify `engine.py` in this branch unless Amish explicitly approves a small additive switch — in which case the diff must be under 15 lines and behind an env flag.

## Sequencing within this branch

1. **Spike LiveKit locally** with docker-compose (`infra/livekit/docker-compose.yml`). Get a phone publishing and a laptop subscribing within the first day.
2. Deploy LiveKit to Fly.io (`infra/livekit/fly.toml`) — TLS, TURN port range exposed, persistent storage for recordings.
3. `services/signaling/` — JWT broker minting LiveKit tokens from Clerk JWTs. ACL: a homeowner can only access their own nodes.
4. `services/pairing/` — code generation, public-key registration, node JWT minting.
5. `vision_pipeline/livekit_source.py` — Python SDK subscriber, yields frames in the existing engine's shape.
6. `infra/go2rtc/` — adapter so an IP cam joins a node room as a publisher.
7. `EXPO_CONFIG.md` — write the doc, hand off to mobile-ux.
8. Hardening: stream restart on disconnect, simulcast tuning, recording retention policy, ed25519 verification of pair messages.
9. Load test: 10 concurrent rooms, 30 viewers each, measure latency.

## Definition of done

- LiveKit reachable on a public TLS URL, TURN reachable.
- Pair a phone in < 30s end-to-end (open app → scan → live).
- p50 glass-to-glass latency on phone-cam → mobile-viewer < 400ms on Wi-Fi, < 800ms over LTE.
- An off-the-shelf IP cam (Wyze v3 or Reolink) joins via go2rtc with one config line.
- All streams gated by JWT. ACL test: homeowner A cannot view homeowner B's stream.
- Brain LiveKit subscriber processes frames at >= 15fps on a M-series MacBook.
- TS types generated.
- `infra/livekit/EXPO_CONFIG.md` published.

## Merge checklist

- [ ] No edits to `vision_pipeline/engine.py`, `vision_pipeline/events.py`, `vision_pipeline/publisher.py`.
- [ ] No edits to `apps/mobile/app.json` (mobile-ux owns it; you wrote the doc).
- [ ] No edits to `action_router/` or other `services/*` subtrees.
- [ ] `requirements.txt` only adds.
- [ ] LiveKit secrets are in env, never committed.
- [ ] CI green; deployed LiveKit reachable from a smoke test.
