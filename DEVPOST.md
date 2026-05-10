## Inspiration

Package theft costs Americans an estimated **$12 billion a year**, and in 2024 alone over 58 million packages were stolen — yet roughly four in five victims never see any law-enforcement follow-up. The smart-doorbell industry's answer has been "send the homeowner a push notification": useful if you're home, useless if you're sitting in a lecture watching the thief jog away in 1080p.

We kept asking the same question: *the camera already saw it — why is the response still manual?* What if the camera could decide, on its own, that something is wrong; describe the suspect in plain English; and **place a phone call** — to the homeowner, to the neighbors, or to the thief themselves? That's ThirdEye.

## What it does

ThirdEye is a decentralized neighborhood vision mesh with **severity-aware response**. A doorbell or security camera streams into the pipeline, and four agents take it from there:

1. **Watcher** (YOLOv8) detects motion in real time and tags people, packages, and vehicles.
2. **Reasoner** (Qwen2-VL) takes the gated frame and produces a natural-language incident description — e.g., *"adult male in a red hoodie and dark jeans, exiting frame eastbound carrying an Amazon package that was not previously on the porch."*
3. **Dispatcher** (FastAPI router) routes the event by **severity tier** — a delivery driver dropping off is tier 1 (logged); someone loitering is tier 2 (homeowner SMS); an active grab-and-go is tier 3 (everyone gets a phone call).
4. **Voice Agent** (powered by **ElevenLabs Conversational AI** + Twilio) synthesizes the call. The homeowner hears a calm, factual briefing in a familiar voice. The thief hears a startling, on-scene line that names the clothing they're wearing and tells them they're on camera.

End to end — porch event to ringing phone — runs in **under three seconds**.

## How we built it

ThirdEye is a four-stage real-time pipeline. We deliberately built each stage as its own service so we could iterate on the prompt, the model, or the voice independently.

**Watcher — YOLOv8 + OpenCV.** A Python service ingests RTSP from any IP camera and runs YOLOv8n at ~30 FPS on a single consumer GPU. We picked the lightest YOLO variant on purpose: the watcher is a *cheap pre-filter*, and every frame it forwards costs us a downstream VLM call. The watcher emits structured signals (person carrying a package-shaped object, lingering >5s inside the porch polygon) rather than raw bounding boxes.

**Reasoner — Qwen2-VL-7B.** Gated frames hit a self-hosted Qwen2-VL endpoint with a chain-of-thought prompt that asks the model to classify the event (delivery / pickup / loiter / theft), describe the subject (clothing, build, direction), and rate its confidence. We chose Qwen2-VL specifically because (a) open weights, (b) 7B fits comfortably on a single GPU, and (c) we cannot pay GPT-4V cents-per-frame on a 24/7 stream. Free-form "describe what's happening" prompts lost badly to the structured chain-of-thought scaffold in our evals.

**Dispatcher — FastAPI router with severity tiering.** A FastAPI service on port 8001 receives the Reasoner's JSON event, applies severity rules, and fans out actions in parallel — log, SMS, voice call. Each tier maps to a different ElevenLabs voice profile and Twilio call template, so a tier-3 confrontation never sounds like a tier-1 receipt confirmation.

**Voice Agent — ElevenLabs Conversational AI + Twilio.** The Voice Agent receives the Reasoner's incident description as a dynamic variable inside an ElevenLabs Conversational Agent. We exposed `incident_description`, `subject_clothing`, and `direction` as client tools so the agent interpolates them naturally inside the spoken script. Twilio places the outbound call. The whole agent definition lives next to the prompts, so design and engineering iterated on it together.

**Frontend — Next.js dashboard + Swift companion.** A web dashboard streams live events with replay and severity overrides; a lightweight Swift app delivers push notifications and one-tap "call me back" for the homeowner.

## Challenges we ran into

The hard problem was **semantic gating, not detection.** A naive "YOLO fires an alert" system has a >90% false-positive rate — every Amazon driver triggers it. Sending every motion frame to Qwen2-VL, on the other hand, would blow up our latency budget and pin the GPU. We landed on a two-stage gate: YOLO emits structured signals only when a person carrying a package-shaped object lingers inside the porch polygon, and only those gated events become VLM calls. This **dropped Reasoner invocations by ~15× without measurable recall loss** on our staged-theft test clips.

The second hardness was **end-to-end latency.** For the on-scene voice line to feel like the camera is *talking to the thief*, the call needs to ring before they're off the property. Targeting sub-three-second porch-to-ring meant streaming the gated YOLO event the instant it fired, kicking off Qwen2-VL inference and Twilio call setup **in parallel**, and feeding the ElevenLabs synthesis the description as soon as it streamed out of the VLM. We hit a **2.4s median** on our test bench.

The third was **getting the voice right.** A robotic monotone reads as a recording and gets ignored. We iterated on ElevenLabs voice settings (stability, similarity, style exaggeration) and on the prompt itself until the on-scene line sounded like a startled human, not a phone tree.

## Accomplishments that we're proud of

- **2.4-second median end-to-end** from porch event to outbound call ringing.
- **~15× reduction in VLM invocations** from the YOLO gate, with no measurable drop in recall on our staged tests.
- **94% correct severity classification** on a hand-labeled set of 50 doorbell clips spanning deliveries, pickups, loitering, and theft.
- A **working live demo**: point the camera at the table, pretend to grab a "package," and your phone rings — in the room, in front of the judge.
- A genuinely **interdisciplinary build**: not just engineering, but a market thesis, a customer pilot list, and a homeowner-insurance partnership pitch built in parallel by our CS (UC Santa Barbara) and business (Kelley School at Indiana) leads.

## What we learned

- **The bottleneck in security AI is not detection — it's semantic understanding under cost constraints.** Gating cheap signals before invoking expensive models is the entire game.
- **VLMs as policy engines** (decide-and-describe) are remarkably effective when you give them structured chain-of-thought scaffolding. Free-form prompts lose every time.
- **ElevenLabs Conversational AI feels qualitatively different from one-shot TTS.** A real-time voice agent that interpolates the suspect's description on the fly is what makes the demo land — and it's what makes the thief actually look up at the camera.
- **Cross-disciplinary teams ship better demos.** Our CS lead built the pipeline; our business lead built the homeowner-insurance pitch deck and a three-customer pilot list before we wrote our first commit. The product *feels* like a product because of that.

## What's next for ThirdEye

- **Edge-deploy the Reasoner.** Quantize Qwen2-VL to fit on a Jetson Orin so the whole pipeline runs on the porch — no upstream GPU dependency.
- **Neighborhood mesh.** Cameras gossip incidents peer-to-peer so a theft caught on one porch alerts the rest of the block in seconds.
- **Insurance partnerships.** A signed `incident.json` is a verifiable claim artifact — we're already in conversations with a regional carrier.
- **Voice consent flows** so neighbors can opt in to receive briefings in a designated family member's voice.
- **Open the gate language** so anyone can write custom severity rules in a small DSL without touching Python.
