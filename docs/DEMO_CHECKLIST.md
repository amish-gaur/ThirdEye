# ThirdEye — Demo Day Checklist

Run through this **top to bottom, in order**, before judging starts.  
Everything is on branch **`action-router`**.

---

## 0. Before you leave home (night before)

- [ ] Both laptops charged, power adapter in bag.  
- [ ] Hotspot available in case venue WiFi blocks ngrok.  
- [ ] Twilio trial: confirm `HOMEOWNER_PHONE` is a **verified** caller ID in the dashboard.  
- [ ] Backup video recorded (one clean run with full audio).

---

## 1. Sumedh's machine — Action Router

### 1a. Start the service
```bash
cd ~/ThirdEye
git checkout action-router && git pull
source .venv/bin/activate
python -m scripts.run_service
# leave this terminal running
```

### 1b. Start ngrok (new terminal)
```bash
ngrok http 8001
```
Copy the **`https://…ngrok-free.dev`** URL.

### 1c. Patch `.env` with the live ngrok URL
Open `.env` and update:
```ini
PUBLIC_BASE_URL=https://YOUR-NGROK-URL-HERE
```
Then restart the service (stop/start step 1a).

### 1d. Verify service is healthy
```bash
curl -s http://127.0.0.1:8001/health | python3 -m json.tool
```
You must see:
```
"status": "ok"
"dry_run": false
"twilio_configured": true
"public_base_url": "https://YOUR-NGROK-URL"   ← must match
```

### 1e. Smoke test voice call
```bash
source .venv/bin/activate
python -m scripts.send_test_event --tier 3
```
Your phone should ring within ~10 seconds. After Twilio's trial intro you should hear the ThirdEye script.

**If call doesn't come:** check `errors` in the JSON response. Most likely cause: ngrok URL stale or `DRY_RUN=true` still set.

---

## 2. Amish's machine — Vision Pipeline

### 2a. Pull latest
```bash
cd ~/ThirdEye
git checkout codex/vision-pipeline-qwen-mps && git pull
source .venv/bin/activate
pip install -r requirements.txt   # only needed first time
```

### 2b. Set `.env` for the demo camera angle
```ini
NODE_ID=node_amish
ACTION_ROUTER_URL=https://YOUR-NGROK-URL-HERE/event   # Sumedh's ngrok URL
MOCK_CLASSIFIER=false
POST_EVENTS=true
DEMO_MODE_THEFT_BIAS=true
SHOW_WINDOW=true
DEBUG_OVERLAY=true
SAVE_FAILURE_ARTIFACTS=true

# Tune zone to the actual camera view — tighter = fewer false positives:
ENTRY_ZONE=0.20,0.35,0.80,0.95

# Thresholds (lower if backpack not detected reliably):
PERSON_CONFIDENCE=0.40
CARRYABLE_CONFIDENCE=0.20
```

### 2c. Quick integration test (mock mode)
```bash
MOCK_CLASSIFIER=true python -m scripts.run_vision
```
Walk in front of the camera carrying a bag.  
You should see **state: CANDIDATE** → **state: SUPPRESSED** in the overlay  
and Sumedh's phone rings within ~15 seconds.  
If no call: check Sumedh's terminal for the POST log line.

### 2d. Switch to real Qwen
```bash
MOCK_CLASSIFIER=false python -m scripts.run_vision
```
Same test — walk in with a backpack, stay in the zone for ~1 second.

---

## 3. Demo order (in front of judges)

1. **"Here's the camera feed"** — show the overlay window (zone box, state label).
2. **Amish walks past the camera without a bag** → state stays IDLE / WATCHING, no call.
3. **Amish walks in with a backpack and stands near the "door"** → overlay shows CANDIDATE → SUPPRESSED.
4. **Sumedh's phone rings** → answer on speaker so judges hear the AI voice alert.
5. **"This is your ThirdEye agent. [description]. Press 1 to notify your neighbors…"**
6. Talk through the architecture: YOLO (detect) → BehaviorTracker (rules) → Qwen (verify) → Router → Twilio.

---

## 4. Fallbacks (in priority order)

| Problem | Fix |
|---------|-----|
| ngrok URL changed (laptop slept) | Re-run ngrok, update `PUBLIC_BASE_URL`, restart router (30s) |
| Call rings but only Twilio intro, then silence | `USE_ELEVENLABS=false` in `.env`, restart router → robot voice |
| ElevenLabs 402 / plan error | Same as above |
| Backpack not detected | Lower `CARRYABLE_CONFIDENCE=0.15`, restart vision |
| Qwen rejected output (visible in Amish's logs) | Check log for "rejected [reject]: …" reason; if "hallucinated location" → normal, wait for next frame |
| Everything fails | Play the backup video |

---

## 5. After demo — cleanup

- [ ] `DRY_RUN=true` in `.env` to avoid accidental calls.
- [ ] Stop ngrok (kills tunnel).
- [ ] Rotate the Twilio Auth Token and ElevenLabs key — both were shared in chat earlier this session.
- [ ] Commit any last demo-day `.env.example` changes to the branch.
