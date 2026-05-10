# Design: ThirdEye — Decentralized Neighborhood Vision Mesh

Hardware dropped (commodity-only thesis). Severity-tiered execution layer added.

- **Branch:** main  
- **Repo:** thirdeye (local; no remote yet)  
- **Status:** PRE-EVENT FINAL  
- **Event:** HackDavis — UC Davis (24h build window)

---

## Problem Statement

Neighborhood-scale events — package theft, late-night loitering, break-ins, **elderly falls, wildfire smoke** — happen in environments where private security cameras are common but **isolated**. Every camera is a closed silo: footage flows to a corporate cloud (Ring → Amazon, Nest → Google, Wyze → unknown), and only the home it's mounted on gets alerted. The signal a *network* of cameras could generate — "someone is walking porch-to-porch at 2am," "an elderly neighbor just fell on her driveway," "smoke just appeared on our block" — is structurally impossible to extract because no two cameras talk without a corporate intermediary. And every camera responds the same way to every event: a single notification stream, regardless of severity.

Three failure modes today:

1. **Cloud-dependent silos** (Ring, Nest, Wyze): privacy-bad, latency-bad (cloud round-trip per alert), $3-15/mo per camera, offline-fragile, **and require buying hardware**.
2. **Single-home privacy projects** (Secluso, RECAM, Ucam, SecuraCV): solve isolation but only at one house. A burglar across five porches is invisible to all five projects independently. An elder who falls between two homes' fields of view goes unseen.
3. **Flat alerting on every product**: Ring, Nest, Citizen all use a single notification stream — every event is a push notification, regardless of whether it's a delivery, a stranger, or an emergency. Result: alert fatigue. Real emergencies get lost in the noise.

ThirdEye is the missing piece: a decentralized, opt-in, on-device camera mesh with **severity-aware response**, running entirely on devices people already own.

---

## What Makes This Cool — Optimized for Hacker Peer Vote

**Critical insight from research: HackDavis grand prize ("Best Hack for Social Good") is decided by hacker peer vote, not judges.** ~950 hackers vote at the demo expo. We optimize for **technical novelty + 30-second memorability + universal-accessibility narrative**. Hackers vote for "wait, you fit a 9B VLM on a Mac, meshed it cryptographically, classified events into severity tiers, AND it runs on any phone with no extra hardware?" not for polished slides.

The "whoa" moments, layered:

1. **Severity-aware execution on stage.** Three back-to-back live demos: (a) a delivery happens — system stays quiet, just a push notification; (b) a theft happens — *the judge's phone rings via Twilio*, AI voice describes the suspect by their hoodie color and offers neighbor notification; (c) an emergency happens — simultaneous cascade fires (911-dispatcher rings, family rings, mesh fans out). Three events, three responses, all in 90 seconds. **The system isn't reactive — it's an agent.**

2. **Multi-mission demo: theft + elder falls + wildfire smoke.** Same software, three Moondream verification prompts. Davis is wildfire country; this lands.

3. **Plain-English semantic search across past clips.** Type *"show me anyone late at night wearing a hood."* CLIP embeddings + MongoDB Atlas Vector return ranked clips. No backend uploads.

4. **The architectural punchline.** "Footage never leaves your home. YOLO at 30fps triggers. Moondream classifies severity. A 200-line Python action router fires the right response — push, voice call, or full emergency cascade. The mesh is Tailscale, peer-to-peer. The only thing that crosses your network is a 200-byte ed25519-signed event blob — never a frame, never a clip. **No hardware to buy. No subscription. Privacy is structural.**"

The eureka other hackers will share: **privacy-as-isolation prevented neighborhood signal; commodity-software VLA + tiered execution + signed metadata-only mesh + opt-in consent dissolves the contradiction — and works on any device.**

---

## Constraints

- **Time:** 24-hour hackathon window. **Submission deadline on Devpost is hard** — confirm the exact cutoff on the official event page each year.
- **Team:** 4 engineers (HackDavis max).
- **Tracks selected (max 4):** Anthropic AI/ML, ElevenLabs, MongoDB Atlas, .tech Domain. **Auto-eligible** (no signup): Best Hack for Social Good (grand prize, peer vote), Most Creative, Most Technically Challenging, Hacker's Choice.
- **No special hardware required for end users.** Hard product constraint: ThirdEye must run on devices people already own (a phone + a laptop). Hardware adds friction that defeats the "available to everyone" thesis we'll argue is what makes ThirdEye better than Ring.
- **Demo equipment** (team-side, not user-side): 2 phones (one per Mac as porch camera), 2 MacBooks (home brains), 1 phone for the "judge's homeowner phone" role, 1 phone for the "911 dispatcher" actor, 1 phone for the "family contact" actor. $20 ring-light. Fake Amazon box. Hoodie. 4 USB-C cables.
- **No footage leaves the home.** Vision (YOLO, Moondream), embedding (CLIP), search (Atlas Vector) all run on the MacBooks. External services receive event metadata only: ElevenLabs (TTS string in, audio out), Anthropic Claude (event description in, narration out), Twilio (call/MMS metadata + pre-generated MP3 URL + clip URL). They never see live frames. Twilio MMS does see the *clip* (8-second MP4) — flagged in the pitch as "this is the one external service that receives video, only for outbound delivery to the homeowner."
- **No real 911 calls.** Hard constraint. EMERGENCY tier calls a teammate playing dispatcher, with that phone's contact ID renamed "911 Dispatch" for visual effect. CA Penal Code §148.3 makes false dispatch reports a misdemeanor.
- **No real Ring/Nest cameras.** Demo uses phones; pitch is "this would run on a Ring or any IP cam — we used phones to demo the architecture and to prove no extra hardware is required."
- **Demo length:** 2 minutes (HackDavis historical).
- **Network:** Tailscale (free ≤100 devices). Backup: ngrok.

---

## Premises

1. **"Available to everyone" is the differentiator.** Ring requires hardware. Nest requires hardware. ThirdEye runs on a phone + a laptop. This is the strongest social-good argument we can make and it lives in the architecture, not the marketing.
2. **Severity-aware response is the second differentiator.** Every existing consumer camera flat-alerts on motion. ThirdEye's tiered execution (AMBIENT / NOTICE / ALERT / EMERGENCY → tier-appropriate response) is the agent vs. watchdog distinction.
3. **Grand prize is peer vote, not judge decision.** Optimize for technical novelty + memorability among 950 hackers.
4. **Official rubric:** "Social Good, Creativity, Presentation + 3 track-specific criteria per opted track." Social Good is **baseline for ALL tracks**.
5. **On-device VLMs are real but not magic.** Moondream 3 alone is too slow and non-deterministic on 16GB M-series for live stage detection (~1.8s/inference, prompt-sensitive, run-to-run variance). YOLOv11n at 9.2ms/inference is the deterministic trigger; Moondream is the verifier-and-classifier called only on triggered frames.
6. **Zero training.** Every model is pretrained off-the-shelf (YOLO COCO, Moondream 3 Preview, CLIP ViT-B/32, Claude API, ElevenLabs API). We change behavior with prompts, not gradients.
7. **Distribution is real:** post-hackathon, open-source on GitHub with one-command setup. Hosted at thirdeye.tech.

---

## Architecture

### Pipeline (one paragraph)

Two MacBooks, each acting as one home's brain, meshed via Tailscale. Each Mac runs a Python service that ingests an RTSP stream from one phone (IP Webcam Android + ffmpeg, OR Larix Broadcaster iOS + RTSP). The service samples frames at 30fps and runs **YOLOv11n** (Ultralytics + MPS backend) for cheap deterministic detection of `person` + `backpack`/`handbag`/`suitcase` (COCO pretrained — zero training). A **15-second rolling frame buffer** (`collections.deque`) holds recent keyframes for clip extraction. When YOLO detects a person near a box-class object for 2 consecutive frames (or matches a fall / smoke heuristic), the trigger fires and **Moondream 3 (int4 quant)** is called once with a structured **severity classifier prompt** that returns JSON: *"Classify into AMBIENT, NOTICE, ALERT, or EMERGENCY. Return tier + confidence + suspect_description + one_line_summary."* The result feeds the **action router** — a 150-LoC Python service that maps tier → response set. Every event is signed (ed25519, Mac's pinned key) before mesh publication. Tier-specific actions execute in parallel: AMBIENT logs and CLIP-embeds; NOTICE sends web push + MMS with bounding-box-annotated photo; ALERT triggers a Twilio outbound voice call (AI describes suspect, asks if homeowner wants neighbors notified) plus MMS with an 8-second clip from the rolling buffer; EMERGENCY fires a simultaneous Twilio cascade — call to "911 dispatcher" (teammate phone) with structured incident report, parallel calls to homeowner + family contact, full mesh broadcast, signed clip locked for evidence chain-of-custody. In parallel on every keyframe: CLIP embedding (~30ms) → MongoDB Atlas Vector for semantic search. A FastAPI service exposes search; a React+Vite **Progressive Web App (PWA)** shows event log + search bar + node map and registers for web push. Three Moondream mission prompts cover porch theft, elder fall (*"did the person fall and not get up?"*), wildfire smoke (*"is there smoke or unusual haze?"*) — each maps to its own severity classifier output.

### Stack

| Layer | Choice |
|-------|--------|
| **Cheap detection (deterministic trigger)** | YOLOv11n via Ultralytics, MPS backend on Apple Silicon. ~9.2ms/inference, ~50fps, ~6MB weights. COCO classes 0/24/26/28 pretrained. Zero training. |
| **Event verification + severity classifier (VLM)** | Moondream 3 Preview, **int4 quantization** (~7.3GB on disk; ~2-5% accuracy hit acceptable). Called only on YOLO-triggered frames. Structured prompt returns `{tier, confidence, suspect_description, one_line_summary, time_elapsed}`. Zero training. |
| **Action router** | ~150 LoC Python service. Tier → response set. Configurable per-homeowner consent flags. Priority queue ensures EMERGENCY actions execute before in-flight lower-tier responses. Cross-tier de-duplication prevents repeat alerts on the same suspect within 60s. |
| **Incident narration** | Anthropic Claude (Sonnet 4.6 default; Haiku 4.5 fallback for speed). Visual description from Moondream → context-aware deterrent script + Twilio call IVR script. Models the **Anthropic AI/ML track** ($750 credits). |
| **Voice (TTS)** | ElevenLabs API. Audio delivered as MP3, served via local ngrok URL → Twilio TwiML `<Play>` tag for outbound calls; also delivered via web push for PWA playback. Models the **ElevenLabs track**. |
| **Outbound voice + MMS** | **Twilio Voice + Programmable Messaging**. Voice calls ring homeowner / 911-actor / family with TwiML IVR ("press 1 to notify neighbors, press 2 to ignore"). MMS sends 8-second MP4 clip + bounding-box-annotated thumbnail. **Twilio is not a HackDavis sponsor** — pure demo investment (~$5 in API credits). |
| **Rolling frame buffer** | Python `collections.deque(maxlen=450)` (15s × 30fps decimated to keyframes). On ALERT/EMERGENCY, action router pulls preceding 8s, encodes to MP4 via ffmpeg, uploads to local ngrok URL for Twilio MMS pickup. |
| **Image annotation** | OpenCV draws YOLO bounding boxes + labels on the event frame for MMS thumbnail (~30 LoC). |
| **Embedding model** | CLIP ViT-B/32 (open-clip-torch). 512-dim, ~30ms/frame. Zero training. |
| **Vector store + search** | MongoDB Atlas (free tier with Atlas Vector Search). Models the **MongoDB Atlas track**. |
| **Mesh transport** | Tailscale (free ≤100 devices, MagicDNS). Backup: ngrok. |
| **Phone-to-Mac stream** | IP Webcam (Android) + ffmpeg, OR Larix Broadcaster (iOS) + RTSP. |
| **Frontend / homeowner alert UI** | React + Vite + Tailwind, deployed as a **Progressive Web App (PWA)**. Web push notifications + audio playback via standard Web APIs — works on any phone or laptop browser, no app install. |
| **Crypto** | ed25519 per Mac with pre-pinned keys. Event metadata + clip hash signed before mesh publication. |
| **Domain** | thirdeye.tech (free with .tech sponsor, models the **.tech track**). |
| **Languages** | Python (vision, mesh, action router, voice services); TypeScript (frontend / PWA). |

---

## Execution Hierarchy

This is the layer that makes ThirdEye feel like an *agent* instead of a motion-activated noisemaker. Existing cameras only have ON/OFF — every event triggers the same alert, leading to fatigue. ThirdEye's tiered execution means the system *cares appropriately* — quiet for routine, loud for theft, full-cascade for emergencies.

| Tier | Trigger examples | Execution |
|------|------------------|-----------|
| **1. AMBIENT** | Person walking past, normal delivery, neighbor at door, vehicle passing | Log to event timeline + CLIP-embed for later semantic search. **Zero notification.** |
| **2. NOTICE** | Stranger lingering >2min with no clear purpose, package dropped without delivery uniform, loitering, suspicious approach | **Web push + MMS** to homeowner with bounding-box-annotated photo + caption (*"Someone's been on your porch for 3 minutes."*). No call. Quiet. |
| **3. ALERT** | Active theft, door handle being tested, unauthorized package pickup, forced approach | **Twilio outbound voice call** with AI describing the suspect by appearance + **MMS with 8-second clip from rolling buffer** + signed mesh broadcast to neighbor nodes. Caller ID: *"ThirdEye."* Homeowner can press 1 to notify neighbors, 2 to ignore. |
| **4. EMERGENCY** | Confirmed break-in, forced entry, fall with no movement >30s, fire / smoke detected | **Simultaneous cascade**: (a) Twilio call to "911 dispatcher" (teammate phone) with structured incident report — address, event, suspect description, time elapsed, cryptographic hash; (b) Twilio call to homeowner; (c) Twilio call to pre-configured family contact; (d) full mesh broadcast to neighbors; (e) signed clip locked for evidence chain-of-custody. |

### The classifier prompt

```
You are a neighborhood security classifier. Analyze the scene.
Return JSON: {
  "tier": 1 | 2 | 3 | 4,
  "confidence": 0.0-1.0,
  "suspect_description": "string (clothing, gender if obvious, distinguishing marks)",
  "one_line_summary": "string",
  "time_elapsed": "string (e.g. '4 seconds ago')"
}
Tiers:
  1 AMBIENT: routine activity, no concern
  2 NOTICE: someone present whose presence may need a glance
  3 ALERT: active concerning behavior (theft, trespass, tampering)
  4 EMERGENCY: physical harm, fire, fall with no response, forced entry
Be conservative. False EMERGENCY classifications cost real-world response capacity.
```

### Why this is the genius layer

- **Existing consumer cameras have one notification stream.** ThirdEye has four. The system's response *fits* the situation.
- **The classifier is on-device.** A cloud system can't make this judgment without seeing your footage. ThirdEye judges severity locally, then only the metadata (tier + summary) leaves the home.
- **The router is auditable.** Open-source 150 LoC. You can read the rules. Ring's escalation logic is opaque corporate code.
- **The cascade saves lives, not just packages.** Tier 4 is the difference between elder-falls-detected-immediately versus elder-found-at-shift-change. Davis is wildfire country — Tier 4 smoke detection is genuinely public infrastructure.

---

## 2-Minute Demo Storyline (3 scenarios, severity hierarchy)

**0:00–0:15 — Hook.** *"What if your security system knew the difference between a delivery person, a thief, and an emergency? Three different events. Three different responses. Watch."*

**0:15–0:35 — Tier 2 (NOTICE) live.** Teammate walks up to phone-camera, drops a package, leaves. On screen: YOLO bbox → Moondream classifies → NOTICE (delivery). The judge's phone gets a *quiet* push: *"Package delivered."* No call. **The system was smart enough not to overreact.**

**0:35–1:10 — Tier 3 (ALERT) live.** Hooded teammate walks up, grabs the package, walks away. Moondream classifies → ALERT. Within 2 seconds: **judge's phone rings via Twilio** — caller ID *"ThirdEye."* Judge answers. AI voice: *"This is your ThirdEye agent. 6 seconds ago, someone in a red hoodie removed a package from your porch and walked north. I've sent the clip to your phone. Press 1 to notify your neighbors, 2 to ignore."* Judge presses 1. MMS clip lands. Mesh broadcast fans out — visible on dashboard.

**1:10–1:35 — Tier 4 (EMERGENCY) recorded.** Pre-recorded fall scenario. Show the simultaneous cascade live on stage with three teammate phones lined up:

- "911 Dispatcher" phone rings → AI: *"This is ThirdEye automated dispatch. Fall detected at 1234 Maple Street. Resident not moving for 30 seconds. Footage hash 0x7F3A... EMS recommended."*
- "Homeowner" phone rings simultaneously
- "Family" phone rings simultaneously
- Dashboard shows mesh broadcast to 4 neighbor nodes

**1:35–1:55 — Architecture punchline.** Diagram: on-device YOLO+Moondream classifies severity → action router fires tier-appropriate response → Twilio + web-push + mesh execute in parallel. *"Classifier and router are 200 lines of Python. Whole stack runs on devices everyone already owns. Footage never leaves your home."*

**1:55–2:00 — Close.** *"Privacy-respecting. Severity-aware. No hardware, no subscriptions. Vote ThirdEye."*

---

## 24h Build Plan (wall-clock relative to hackathon start)

Sleep rotation mandatory. Backup demo video must exist by **hour 12** of the build. Eng 2 carries the heaviest scope (action router + Twilio + voice cascade) — Eng 4 swings in for help during hours 6–10.

| Build hours | Eng 1 — Vision | Eng 2 — Execution layer | Eng 3 — Frontend / PWA | Eng 4 — Demo + Glue |
|-------------|----------------|-------------------------|------------------------|---------------------|
| 0–2 | Ultralytics+MPS install, YOLOv11n smoke test on demo Mac | Tailscale auth, Anthropic+ElevenLabs+Twilio API smoke tests, severity-classifier prompt draft | Vite + PWA scaffold (manifest + service worker), web-push subscription stub | Phone-as-camera setup + RTSP stream test, demo room scout |
| 2–6 | YOLO → frame buffer → person+box trigger working; rolling 15s deque integrated | Moondream 3 int4 loaded; severity classifier prompt → JSON parse; 3-mission tuning | Web push end-to-end (Mac → phone receives + vibrates + plays audio); event log UI | Phone stream → Mac inference end-to-end on both Macs |
| 6–10 | Multi-mission prompts (theft/fall/smoke) + false-positive guards | **Action router (tier dispatch); ed25519 signing; Claude API integration; ElevenLabs MP3 generation; Twilio Voice (TwiML `<Play>`); Twilio MMS with clip + annotated thumbnail; image annotation via OpenCV** — Eng 4 helps with ngrok URL hosting | CLIP embedder + MongoDB Atlas Vector schema, 50 sample clips indexed; **opt-in consent flow** | Help Eng 2 with ngrok for Twilio media URLs; first end-to-end run-through; **record backup demo video by hour 12** |
| 10–14 | Edge cases: poor light, multi-person frames, prompt failure modes | Voice cascade: 911-actor → homeowner → family parallel ringing; pre-cached fallback audio for Twilio failover; consent flag UI hooks | Search UI + ranked clip player; dashboard flash-red animation; .tech domain wiring (thirdeye.tech) | Demo dry-run #1. **Sleep rotation: 2 of 4 sleep hours 12–16.** |
| 14–18 | Final detection tuning per tier (more conservative on EMERGENCY) | Tier transition tuning; cross-tier de-duplication; Twilio failover plan | Final UI polish (CUT: framer-motion, Mapbox) | Demo dry-runs #2–3, pitch script lock |
| 18–22 | False-positive thresholds | Voice agent script polish; Twilio call-routing edge cases | Demo deck slides, Devpost project page draft | Demo dry-runs #4–5, deck final, **other 2 of 4 sleep hours 16–20** |
| 22–24 | Buffer / bug bash | Buffer / bug bash | Devpost project page final | **Submit to Devpost before the official cutoff** with backup video, slides, repo, 4-track selection |

### Cuts (do not build)

Mapbox node map (use static SVG), framer-motion polish, two-phone-per-Mac scaling, real ed25519 key distribution UX (pre-pin keys), threshold cryptography (slide-only stretch), face recognition (privacy-fragile), native mobile apps (PWA covers it), real-time conversational AI on Twilio call (use IVR press-1/press-2 instead).

**Tracks selected at submission (4 max):** Anthropic AI/ML / ElevenLabs / MongoDB Atlas / .tech Domain. **Auto-eligible:** Best Social Good (grand prize, peer vote), Most Creative, Most Technically Challenging, Hacker's Choice.

---

## Stretch Goals (only if MVP holds by hour 14)

- **Solana ed25519 hash anchor** (~2h, swap into 4th selected track if shipped): Merkle root of event hashes anchored to Solana every 10 min. Tamper-evident chain-of-custody. Adds **Solana track**.
- **Auth0 neighbor-identity layer** (~3h): manage opt-in consent + neighbor verification with Auth0. Adds **Auth0 track**.
- **Real-time conversational AI on Twilio call** (~4h, slide-only if not shipped): Twilio Media Streams + ElevenLabs streaming → homeowner can actually converse with the AI ("notify Sarah next door specifically").
- **Threshold-signed clip release** (~3h, ~150 LoC): m-of-n ed25519 (3-of-5 neighbors must sign to decrypt a clip). Slide-only flex if not built.

---

## Pitch Deck (5 slides — backup if live demo fails)

1. **Title** — ThirdEye. *"Privacy-respecting neighborhood vision mesh. Severity-aware response. Runs on devices you already own."*
2. **Problem** — Cloud silos require hardware + subscriptions; flat-alerting causes fatigue; no project handles neighborhood-scale signal.
3. **Insight** — Privacy-as-isolation prevented neighborhood signal. Severity-aware tiered execution + commodity-software VLA + signed metadata-only mesh dissolves it.
4. **Architecture** — diagram (2 homes, Tailscale, YOLO+Moondream, severity classifier → action router → tier-appropriate response, web-push/Twilio/mesh, Atlas Vector).
5. **Demo + close** — three-tier demo screenshot grid + multi-mission impact (theft/falls/fires) + roadmap.

---

## Open Questions (verify in a dedicated pre-build window)

A prior dry-run was missed. **Run these checks before hacking starts** so each "no" answer still has a fallback.

- **YOLOv11n at 30fps on demo Mac with phone RTSP input?** Verify early. Fallback: drop to YOLOv8n or 15fps.
- **Moondream 3 int4 fits and responds <2s on demo Mac?** Verify with 480p frame + 3 mission prompts. Fallback: skip Moondream, use YOLO confidence + a rule-based event ("box was there → person near box → box gone for 3 frames"). Claude can still narrate.
- **Does Moondream return well-formed JSON for the severity classifier prompt?** Verify before relying on it. If JSON parsing is unreliable, switch to a multiple-choice prompt ("Reply with exactly one word: AMBIENT, NOTICE, ALERT, or EMERGENCY") + separate prompts for description.
- **Does Twilio outbound call ring the target phone within 3 seconds of API call?** Verify with a teammate's phone in another room. Target: phone rings within 3s, AI voice plays within 4s. Fallback: pre-cached audio + simpler IVR.
- **Does Twilio MMS deliver an 8-second MP4 video clip on demo network within 5 seconds?** Verify on target networks. Twilio MMS has a **5MB attachment limit** — confirm clip size fits (8s at 480p ~3MB).
- **Does ngrok hold a stable public URL for Twilio media pickup during the demo?** Verify under load. Fallback: pre-upload audio/video to S3 / Cloudflare R2.
- **Does web push + audio playback work on iOS Safari + Android Chrome?** Verify on both. iOS web push requires PWA "Add to Home Screen" + a recent Safari version; check current Apple docs. Fallback: WebSocket + pre-loaded browser tab.
- **Does Claude API respond <500ms for 50-token script generation?** Time it. Fallback: Haiku 4.5.
- **Does ElevenLabs API respond <1s for short scripts?** Time it. Fallback: pre-cache 5 common phrases as MP3.
- **Does MongoDB Atlas free tier handle 1k vector inserts + queries on demo network?** Verify or fall back to sqlite-vec.
- **Tailscale auth at venue with congested shared wifi?** Pre-auth all devices beforehand. Personal hotspot as backup.
- **Demo room lighting?** Bring the $20 ring-light. Test in the actual demo room during setup hour.
- **Phone battery life?** USB-C plugged the whole time.

---

## Success Criteria

- [ ] **All 4 severity tiers execute correctly in dry-runs.** AMBIENT logs silently. NOTICE pushes + MMS only. ALERT triggers Twilio call + clip. EMERGENCY triggers parallel cascade (911-actor + homeowner + family + mesh).
- [ ] **End-to-end Tier-3 latency <4 seconds** from theft frame to homeowner phone ringing.
- [ ] **MMS clip delivery <6 seconds** from event to clip on phone.
- [ ] **No false EMERGENCY classifications** in 50 dry-run frames (false-positive cost is high).
- [ ] Two simultaneous "homes" mesh-broadcast events cleanly via Tailscale.
- [ ] Semantic search returns relevant clips within 1 second on a query typed live.
- [ ] **No special hardware required** — verified by setting up a fresh phone + laptop with no extra kit and running the full flow.
- [ ] No live frame leaves a Mac during the demo path (verify with Wireshark/Little Snitch in prep). MMS clip is the one acknowledged exception, flagged in pitch.
- [ ] Demo runs cleanly twice in dry-runs without manual intervention.
- [ ] Submitted to Devpost before the official cutoff with: 2-min video, README, GitHub link, architecture diagram, 4 selected tracks.
- [ ] Wins at least one track. Stretch: wins Best Hack for Social Good (peer vote → grand prize).

---

## Distribution

- **At demo:** running on two MacBooks + two phones (camera role) + three phones (homeowner / 911-actor / family roles, ideally a judge's + two teammates' phones). Devpost video as backup.
- **Post-hackathon:** open-source on GitHub (MIT). One-command setup script for the Mac side. PWA for the phone side — anyone can register at thirdeye.tech and install with two taps.
- **Real-world install path:** PWA covers iOS + Android out of the box. Mac brain is Homebrew-installable. **Zero friction adoption** — that's the thesis.
- **CI/CD:** GitHub Actions for Python tests + frontend build on every push.

---

## Next Steps (night before / morning of the build)

Use whatever time you have left before the hackathon clock starts. Final prep window.

### Pre-build checklist

1. **Pre-auth all APIs:** Anthropic, ElevenLabs, **Twilio**, MongoDB Atlas, GoDaddy/.tech, Tailscale on every team member's Mac. Save tokens to a shared 1Password vault. Twilio: provision a phone number, verify caller ID is editable to "ThirdEye."
2. **Verify the severity-classifier JSON prompt.** Run 20 test frames through Moondream 3 with the classifier prompt. Confirm well-formed JSON. If unreliable, switch to multiple-choice + separate description prompt.
3. **Verify Twilio outbound call latency on cellular AND wifi.** Target <3s ring, <4s AI voice. Test with a teammate's phone in another room.
4. **Verify Twilio MMS with 8-second 480p MP4 attachment.** Confirm <5MB and <6s delivery.
5. **Verify web push + audio on iOS Safari + Android Chrome.** Decide PWA vs WebSocket fallback before the venue, not at the venue.
6. **Run the dry-run we missed:** phone RTSP → YOLO + Moondream classifier → action router → Twilio call + MMS + mesh + web push. Time the full loop end-to-end.
7. **Memory check on demo Mac:** Moondream 3 int4 ~7GB. Verify it loads. Run 10 inferences with 3 mission prompts. Log latency variance.
8. **Pre-write detection prompts:** 5-10 for theft, 3-5 for elder falls, 2-3 for smoke. Commit to `prompts.txt`. Pick the best set during integration.
9. **Buy demo props:** fake Amazon box, hoodie, $20 ring-light, 4 USB-C cables.
10. **Pitch script + rehearsal:** 2 minutes. Memorize. One designated speaker. Rehearse multiple times before the build. Lead with "available to everyone + severity-aware."
11. **Reserve thirdeye.tech** with .tech sponsor (free, ~5 min).
12. **Pre-form team roles:** Eng 1 vision, **Eng 2 execution layer (severity classifier + action router + Twilio + voice — heaviest scope)**, Eng 3 frontend/PWA/web-push, Eng 4 demo/glue/streaming + Eng 2 helper during hours 6–10. Each owns their column.

### Hour zero (build starts)

- Eng 1+2 → Tailscale + API key smoke tests. Eng 3 → Vite + PWA scaffold. Eng 4 → phone RTSP setup on both Macs.
- After the first half-day: full pipeline integration, sleep rotation, backup video by hour 12 of the build.

### Submission deadline

- Submit to Devpost well before the posted cutoff (leave buffer).
- At demo expo / peer vote: be at the table, demo the three-tier execution on repeat. Hand out a 1-pager with "github.com/<you>/thirdeye" + a QR code linking to thirdeye.tech where any visitor can install the PWA on their own phone in 30 seconds. **The PWA install on a judge's phone IS the demo.**

---

## Research Findings Applied (internal deep research + product pivots)

Parallel research passes validated core assumptions. Two product pivots followed: (1) drop hardware to honor "available to everyone" thesis, (2) add severity-tiered execution layer for "agent vs noisemaker" differentiation. Critical corrections:

- **Moondream alone was the wrong call for detection.** Moondream 3 on 16GB Mac M2 = ~1.8s/inference + non-deterministic ([HN](https://news.ycombinator.com/item?id=45391444), [GitHub #251](https://github.com/vikhyat/moondream/issues/251)). YOLOv11n (~9.2ms, deterministic) triggers; Moondream verifies and classifies severity. Zero training across the stack.
- **Vapi is not a confirmed HackDavis sponsor — replaced with ElevenLabs (which is).** Twilio added for outbound voice + MMS (not a sponsor — pure demo investment).
- **Hardware dropped intentionally.** Davis Autonomy Club's $10k VLA prize requires "physical robotic behavior" — we knowingly forfeit because requiring users to buy hardware defeats "available to everyone." The VLA loop survives in software (severity classifier + action router + Twilio + web push + mesh). Net effect on grand-prize odds: positive, peer voters reward universal accessibility.
- **Severity-tiered execution added** to differentiate from flat-alert competitors (Ring, Nest, Citizen). Four tiers (AMBIENT/NOTICE/ALERT/EMERGENCY) → tier-specific response. The classifier is on-device Moondream; the router is 150 LoC Python.
- **Grand prize is hacker peer vote, not judge decision.** Optimize for technical novelty + 30-second memorability + universal-accessibility narrative. Grand prize hardware varies by year — check the official prize page.
- **Demo length: 2 minutes.** Restructured into 3 scenarios (NOTICE / ALERT / EMERGENCY) showing the severity hierarchy live.
- **Multi-mission framing:** theft + elder falls + wildfire smoke. Same architecture, three Moondream prompts. Davis is wildfire country.
- **Official rubric:** "Social Good, Creativity, Presentation + 3 track-specific criteria." Social Good baseline for ALL tracks.
- **4 tracks selected:** Anthropic AI/ML / ElevenLabs / MongoDB Atlas / .tech.
- **24-hour window is sharp** — start and end times are fixed per event; confirm on Devpost.

**Sources:** current [HackDavis](https://www.hackdavis.io) site and Devpost listing for the active event; [Moondream Photon benchmark](https://moondream.ai/blog/photon-1-2-0-update); [YOLO MacBook M3 benchmarks](https://hexdocs.pm/yolo/macbook_air_m3.html); past HackDavis Devpost galleries.
