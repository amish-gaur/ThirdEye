# Wiring the Theft Detector → SafeWatch Action Router

> **Read this whole file before touching code.** It's the contract between
> Amish's vision pipeline (theft detector + best-frame capture) and Aditya's
> action router (Twilio voice fan-out + iMessage fan-out). Once your code
> matches the contract below, a confirmed theft event triggers ringtones on
> all 4 demo phones and iMessages with the suspect frame attached, all in
> ~3 seconds.

## Why the architecture is split across two Macs

We use **macOS Messages.app via AppleScript** to send the iMessage fan-out.
That binding lives on Aditya's MacBook because:

1. Messages.app must be signed into a real iCloud account, with the
   homeowner's Apple ID. Aditya's account is already signed in, the
   Davishacks group chat is already paired, and macOS Automation
   permission has already been granted to his Terminal.
2. iMessage fan-out doesn't go through any cloud service we control —
   the laptop literally drives the local Messages.app process.

Therefore: **Amish's vision pipeline must reach over the network to
Aditya's Mac** when it confirms a theft. The action router on Aditya's
machine is exposed via ngrok and accepts (a) JSON event POSTs and
(b) multipart frame uploads.

```
   Amish's Mac                            Aditya's Mac
   ───────────                            ────────────
   vision_pipeline                        action_router (FastAPI :8001)
   theft_tracker.py ─┐                  ┌──┐  /upload    → saves to media/
                     │   ngrok HTTPS    │  │  /event     → execute_action()
   "THEFT_CONFIRMED" ├─────────────────▶│  │  /media/*   → Twilio fetches MP3
   best frame.jpg ───┘                  └──┤              from here
                                            ├─▶ ElevenLabs (narration MP3)
                                            ├─▶ Twilio (4 parallel calls)
                                            └─▶ Messages.app (4 iMessages)
```

## Step 0 — Get the live ngrok URL from Aditya

Free-tier ngrok URLs change on every restart. Before running anything,
ask Aditya for the current `PUBLIC_BASE_URL` and put it in `.env`:

```bash
# Amish's .env
ACTION_ROUTER_BASE_URL=https://d7ea-128-120-84-76.ngrok-free.app
```

(That's the URL in use right now; confirm with Aditya in case it rotated.)

Verify it before writing any code:

```bash
curl -s "$ACTION_ROUTER_BASE_URL/health" | jq .
# Expect: {"status":"ok","twilio_configured":true,"elevenlabs_play_enabled":true,...}
```

## Step 1 — Capture the best frame at THEFT_CONFIRMED

Add this to `vision_pipeline/theft_tracker.py` (or wherever your state
machine emits the THEFT_CONFIRMED transition). Drop in this helper near
the top of the module:

```python
# vision_pipeline/theft_tracker.py
from pathlib import Path
import cv2
import numpy as np
import time
import uuid

_BEST_FRAME_DIR = Path(__file__).resolve().parent.parent / "media" / "frames"


def save_best_frame(frame_bgr: np.ndarray, incident_id: str) -> Path:
    """Persist the canonical 'this is the suspect' frame for an incident.

    Called once per incident at the moment the state machine reaches
    THEFT_CONFIRMED. Picks the active suspect frame (the one the engine
    currently has buffered — already past the YOLO + Qwen pipeline, so
    person/package boxes are valid), JPEG-encodes at quality 92, and
    returns the path. The action router will pull this off disk to
    attach to the iMessage fan-out.
    """
    _BEST_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    out = _BEST_FRAME_DIR / f"{incident_id}_{int(time.time())}.jpg"
    ok = cv2.imwrite(str(out), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"cv2.imwrite failed for {out}")
    return out
```

**Best-frame heuristic for V2** (skip for tonight, but worth noting): instead
of "the frame at the moment of THEFT_CONFIRMED," keep a rolling buffer of
~30 recent frames during the incident window and pick the frame with
`max(face_det_score * person_yolo_conf * (1 - laplacian_blur))`. That
gives you "best face shot" instead of "frame at theft moment." For the
demo, the latter is good enough — at the moment the package leaves the
zone, the suspect is usually mid-grab and clearly framed.

## Step 2 — Upload the frame to Aditya's Mac

```python
# vision_pipeline/theft_tracker.py (continued)
import os
import requests


def upload_frame_to_action_router(local_path: Path) -> str:
    """POST a JPEG to /upload and return the absolute path on Aditya's Mac.

    The returned path is what you set `clip_path` to in the /event POST —
    the action router resolves it locally on its own filesystem when it
    runs the AppleScript to attach the frame to the iMessage.
    """
    base = os.environ["ACTION_ROUTER_BASE_URL"].rstrip("/")
    with local_path.open("rb") as f:
        r = requests.post(
            f"{base}/upload",
            files={"file": (local_path.name, f, "image/jpeg")},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["path"]   # e.g. "/Users/aditya/.../media/abc12345_inc42.jpg"
```

## Step 3 — Fire the event

The action router's `execute_action` entry point lives at `POST /event`.
The contract is documented at the top of `action_router/router.py` — read
it, but the short version is below. Tier 4 = EMERGENCY = 4 parallel
Twilio calls + 4 iMessages with frame attached.

```python
# vision_pipeline/theft_tracker.py (continued)
import json


def trigger_theft_alert(
    self,
    *,
    frame_bgr,                  # the np.ndarray frame from the engine
    incident_id: str,           # stable per real-world theft (dedup'd 3min)
    suspect_description: str,   # e.g. "tall man in red hoodie and dark jeans"
    one_line_summary: str,      # e.g. "person took a package and walked away"
    scene: str,                 # e.g. "the front porch"
    confidence: float,          # Qwen confidence in [0,1]
    behavior_pattern: str = "taking_item",  # see BEHAVIOR_PATTERN_MAX_TIER
    yolo_classes: list[str] | None = None,  # e.g. ["person", "backpack"]
):
    """End-to-end: save best frame, upload, POST event. Call once per
    confirmed theft from the THEFT_CONFIRMED transition. Idempotent on
    `incident_id` (router dedups within 3 minutes)."""

    base = os.environ["ACTION_ROUTER_BASE_URL"].rstrip("/")

    # 1. Save and upload the suspect frame.
    frame_path = save_best_frame(frame_bgr, incident_id)
    try:
        remote_path = upload_frame_to_action_router(frame_path)
    except Exception as exc:
        log.warning("frame upload failed; firing event without attachment: %s", exc)
        remote_path = None

    # 2. POST the event. tier=4 fires the full T4 EMERGENCY playbook.
    payload = {
        "tier": 4,
        "tier_name": "EMERGENCY",
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "incident_id": incident_id,
        "behavior_pattern": behavior_pattern,
        "confidence": confidence,
        "scene": scene,
        "suspect_description": suspect_description,
        "one_line_summary": one_line_summary,
        "time_elapsed": "just now",
        "yolo_classes": list(yolo_classes or ["person"]),
    }
    if remote_path:
        # The action router's _fanout_imessage reads clip_path off the
        # event and passes it as the AppleScript attachment. Path is
        # absolute on Aditya's Mac — that's what /upload returned.
        payload["clip_path"] = remote_path

    r = requests.post(f"{base}/event", json=payload, timeout=15)
    r.raise_for_status()
    log.info("Fired theft alert: %s", r.json().get("actions"))
    return r.json()
```

## Step 4 — Wire it into the state machine

Wherever your theft state machine reaches `THEFT_CONFIRMED` — most likely
inside `theft_tracker.py` in the `_advance_state(...)` or equivalent
method — call `trigger_theft_alert(...)` with the current frame and the
incident's metadata. **Fire once per state transition, not once per
frame** — the router dedups within 3 minutes but spamming /event burns
ngrok-free's request budget and creates spurious Twilio API calls.

Pseudocode:

```python
def _advance_state(self, evidence: TheftEvidence, frame_bgr: np.ndarray):
    new_state = self._next_state(evidence)
    if new_state == State.THEFT_CONFIRMED and self.state != State.THEFT_CONFIRMED:
        # First entry into THEFT_CONFIRMED — fire the alert exactly once.
        try:
            self.trigger_theft_alert(
                frame_bgr=frame_bgr,
                incident_id=evidence.incident_id,
                suspect_description=evidence.qwen_description,
                one_line_summary=evidence.qwen_summary,
                scene=evidence.zone_label or "the front porch",
                confidence=evidence.qwen_confidence,
                behavior_pattern=evidence.behavior_pattern,
                yolo_classes=list(evidence.detected_classes),
            )
        except Exception:
            log.exception("theft alert fan-out failed (state still advanced)")
    self.state = new_state
```

## Step 5 — Test it without the camera

Before running the full vision pipeline, prove the wire works:

```bash
# Health check
curl -s "$ACTION_ROUTER_BASE_URL/health" | jq .twilio_configured
# Expect: true

# Upload a fake frame
curl -s -F "file=@/path/to/any.jpg" "$ACTION_ROUTER_BASE_URL/upload" | jq .
# Expect: {"path":"/Users/aditya/.../media/<rand>_<name>.jpg","url":"...","size":N}

# Fire a synthetic T4 event referencing that uploaded path
ABS_PATH=$(curl -s -F "file=@/path/to/any.jpg" "$ACTION_ROUTER_BASE_URL/upload" | jq -r .path)
curl -s -X POST "$ACTION_ROUTER_BASE_URL/event" \
  -H "Content-Type: application/json" \
  -d "$(cat <<EOF
{
  "tier": 4,
  "tier_name": "EMERGENCY",
  "event_id": "evt_smoke_$(uuidgen | tr A-Z a-z | head -c 12)",
  "incident_id": "inc_smoke_$(uuidgen | tr A-Z a-z | head -c 12)",
  "behavior_pattern": "taking_item",
  "confidence": 0.92,
  "scene": "the front porch",
  "suspect_description": "tall man in red hoodie and dark jeans",
  "one_line_summary": "person took a package and walked away",
  "time_elapsed": "just now",
  "yolo_classes": ["person","backpack"],
  "clip_path": "$ABS_PATH"
}
EOF
)" | jq .
# Expect: {"tier":4,"actions":["call_*","imessage_4/4",...],"calls":[...],"messages":[...]}
```

If `actions` includes `imessage_4/4` and `calls` has 3 SIDs, **every demo
phone is now ringing AND has the test image in iMessage.** That proves
the entire wire end-to-end without needing the camera, Qwen, or YOLO.

## Common pitfalls

* **"My event POST 200s but no phone rings."** Check `payload.get("tier")`
  is an int, not a string. The router coerces strings but only the int
  path is fully tested. Same for `confidence` — pass a float, not "0.92".
* **"iMessage works but no attachment shows up."** The `clip_path` you
  put in the event must be the path returned by `/upload` (absolute on
  Aditya's Mac), not the local path on your Mac. The router runs
  AppleScript locally and can only attach files that exist locally.
* **"One of four calls drops with error 10004."** New Twilio account
  occasionally drops 1 of N parallel calls; the test script auto-retries
  with a 7-second settle window. The router does NOT auto-retry yet —
  if you see this happen during demo, the test script
  (`scripts/test_concurrent_calls.py`) is the safer path; we can port the
  retry into `router._tier_emergency` later.
* **"ngrok URL changed."** Aditya restarts ngrok every time he reboots.
  Always pull the current URL from him before testing — health-check
  first.
* **"My .env says PUBLIC_BASE_URL=...localhost..."** That's Aditya's
  config knob, not yours. You only need `ACTION_ROUTER_BASE_URL` on your
  side. Do not try to start your own action_router — there's only one.

## What the router does after `/event`

For situational awareness, here's the full T4 sequence triggered by your
single POST:

1. Idempotency check on `incident_id` (3-minute TTL). Duplicate → no-op.
2. Tier coercion + behavior-pattern clamp (e.g. `walking_through` clamps
   to tier 1 even if you sent tier 4).
3. Confidence-floor check (default 0.55 for T4) — below floor downgrades.
4. Generate narration via Anthropic (`narration.py`) → ElevenLabs MP3 to
   `MEDIA_DIR/alert_<uuid>.mp3` → Twilio fetches over ngrok.
5. Place 3 parallel Twilio voice calls (homeowner + family + dispatch
   slots from `.env`) via `_tier_emergency`. Inline TwiML `<Play>` of the
   ElevenLabs MP3.
6. Fire iMessage fan-out via `_fanout_imessage` to every phone in
   `IMESSAGE_RECIPIENTS`. Includes severity badge, summary, scene,
   suspect description, confidence — and the uploaded `clip_path` as
   attachment.
7. Return JSON receipt with all SIDs, iMessage delivery flags, and any
   errors.

Total wall-clock ≈ 3-5 seconds. Twilio call SIDs are returned synchronously
even though the actual ringing happens on Twilio's side after the API
returns 201.

## Files to read on the action router side (for reference)

* `action_router/router.py` — execute_action, tier handlers, dedup,
  `_fanout_imessage`. Top docstring has the canonical event schema.
* `action_router/imessage.py` — AppleScript driver. Each recipient is a
  separate osascript invocation; sequential by design (Apple drops
  parallel sends).
* `action_router/service.py` — FastAPI routes: /health, /event, /upload,
  /media/*, /voice/alert-response (Twilio IVR callback).
* `scripts/test_concurrent_calls.py` — bypass-router smoke test that
  fires 4 parallel calls + 4 iMessages. Useful for tuning the voice
  script before involving the vision pipeline.
* `scripts/send_test_event.py` — POST a synthetic event through the full
  router. Same path your code will take at runtime.

That's it. Wire steps 1-4, run the test in step 5, and a confirmed theft
becomes 4 ringing phones + 4 iMessages with the suspect's face attached.
