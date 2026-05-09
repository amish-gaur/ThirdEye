# SafeWatch — Vision Pipeline (Person 1)

YOLO triggers on `person`, Qwen2-VL classifies severity, and the pipeline emits the exact JSON the action router consumes at `/event`.

## Run locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python vision_engine.py --source 0
```

This branch is tuned for Apple Silicon: both YOLO and Qwen2-VL are moved to `mps`, and the OpenCV loop is explicitly throttled to 10 FPS to avoid thermal runaway during local webcam ingest. Use mock mode for safe integration testing:

```bash
export MOCK_CLASSIFIER=true
python vision_engine.py --source 0
```

To test without calling the router:

```bash
python vision_engine.py --source 0 --no-post
```

To point at the teammate service:

```bash
export ACTION_ROUTER_URL=http://127.0.0.1:8001/event
python vision_engine.py --source 0
```

## Output contract

Every successful classification prints and optionally POSTs:

```json
{
  "event_id": "evt_...",
  "node_id": "node_local",
  "tier": 3,
  "tier_name": "ALERT",
  "confidence": 0.82,
  "suspect_description": "person in red hoodie",
  "one_line_summary": "person took package from porch",
  "time_elapsed": "0.84s",
  "timestamp": 1715301234.567,
  "frame_seq": 4821,
  "yolo_classes": ["person"],
  "clip_hash": null,
  "raw_classifier": "{...}"
}
```

## Safe testing guidance

- `MOCK_CLASSIFIER=true`: skips Qwen2-VL loading entirely and emits a deterministic Tier 3 event after the YOLO person trigger.
- Default classifier model: `Qwen/Qwen2-VL-2B-Instruct` via `transformers`.
