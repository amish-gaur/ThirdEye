# SafeWatch — Action Router (Person 2)

Consumes the JSON event emitted by the vision pipeline and makes the real world react: Claude → ElevenLabs → Twilio.

> **Contract with Person 1:** the router only consumes the JSON described in [§ Event schema](#event-schema). It runs entirely standalone against `scripts/send_test_event.py` until the vision branch is ready.

---

## Setup

```bash
cd /path/to/ThirdEye
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env       # fill in API keys + phone numbers
```

You need real keys for **Anthropic**, **ElevenLabs**, and **Twilio**, plus a provisioned Twilio number. While you're getting them, leave `DRY_RUN=true` in `.env` and the whole pipeline will run end-to-end without making real API calls.

---

## Run end-to-end (local)

Two terminals:

```bash
# Terminal A — service (FastAPI on :8001)
source .venv/bin/activate
python -m scripts.run_service
```

```bash
# Terminal B — fire one event of each tier
source .venv/bin/activate
python -m scripts.send_test_event --tier 2
python -m scripts.send_test_event --tier 3
python -m scripts.send_test_event --tier 4
```

For the Tier 3 / 4 calls to actually ring, Twilio must be able to reach your local FastAPI to fetch the ElevenLabs MP3:

```bash
# Terminal C
ngrok http 8001
# copy the https URL into PUBLIC_BASE_URL in .env, then restart Terminal A
```

---

## Step-by-step smoke tests (the four steps from the build plan)

```bash
# Step 1: API vault - prints the loaded config (redacted)
python -m scripts.show_config

# Step 3a: Claude only - prints the script for a hardcoded ALERT event
python -m scripts.test_narration --tier 3

# Step 3b: ElevenLabs only - synthesizes ./media/test.mp3
python -m scripts.test_tts --text "This is a SafeWatch test."

# Step 4a: Twilio <Say> only - rings HOMEOWNER_PHONE with a static sentence
python -m scripts.twilio_call_say --to "$HOMEOWNER_PHONE" --text "SafeWatch test call."

# Step 4b: Twilio <Play> with the ElevenLabs MP3 - rings HOMEOWNER_PHONE
python -m scripts.twilio_call_play --to "$HOMEOWNER_PHONE" --text "Red hoodie took your package six seconds ago."
```

---

## Tier behavior

| Tier | Behavior |
|------|----------|
| **1 AMBIENT** | Log only. No external calls. |
| **2 NOTICE** | Twilio SMS to `HOMEOWNER_PHONE` with summary. |
| **3 ALERT** | Claude → ElevenLabs → Twilio outbound `<Play>` call to `HOMEOWNER_PHONE`. Falls back to `<Say>` with the same script if ElevenLabs fails. |
| **4 EMERGENCY** | Same script, **parallel** Twilio calls to `EMERGENCY_DISPATCH_PHONE` (teammate playing 911), `HOMEOWNER_PHONE`, and `FAMILY_PHONE`. |

Set `DRY_RUN=true` to log every action without dialing.

---

## Event schema (input)

Person 1's vision pipeline POSTs this JSON to `/event`:

```json
{
  "event_id":            "evt_8a91…",
  "node_id":             "node_local",
  "tier":                3,
  "tier_name":           "ALERT",
  "confidence":          0.82,
  "suspect_description": "person in red hoodie",
  "one_line_summary":    "person took package from porch",
  "time_elapsed":        "just now",
  "timestamp":           1715301234.567,
  "frame_seq":           4821,
  "yolo_classes":        ["person", "backpack"],
  "clip_hash":           null,
  "raw_classifier":      "..."
}
```

Only `tier`, `suspect_description`, `one_line_summary`, and `time_elapsed` are required. Everything else is optional and used for logging / downstream integrations.

---

## Module layout

```
action_router/
├── config.py        # env-driven Config dataclass (Step 1)
├── router.py        # execute_action(event_json) + tier dispatch (Step 2)
├── narration.py     # Claude script generator (Step 3a)
├── tts.py           # ElevenLabs MP3 synthesizer (Step 3b)
├── voice.py         # Twilio outbound call: place_call_say + place_call_play (Step 4)
├── messaging.py     # Twilio SMS for Tier 2
├── twiml.py         # Pure TwiML XML builders (unit-tested)
└── service.py       # FastAPI app: /event, /media/*, /health
```

---

## Demo-day checklist (Person 2 only)

- [ ] `pip install -r requirements.txt` clean on demo Mac
- [ ] `.env` populated with real Anthropic / ElevenLabs / Twilio keys
- [ ] Twilio number verified, caller ID editable to "SafeWatch"
- [ ] `python -m scripts.show_config` shows everything green
- [ ] `python -m scripts.test_narration --tier 3` returns a sensible script
- [ ] `python -m scripts.test_tts --text "..."` writes a playable MP3
- [ ] `python -m scripts.twilio_call_say --to <my phone>` actually rings
- [ ] `python -m scripts.twilio_call_play --to <my phone>` rings AND plays the MP3 (requires ngrok up + `PUBLIC_BASE_URL` set)
- [ ] `pytest -q` passes
- [ ] End-to-end: `send_test_event --tier 3` → judge phone rings within 4s
- [ ] Hand off `/event` URL to Person 1 for vision-side integration
