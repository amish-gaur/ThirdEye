# ThirdEye / SafeWatch

Decentralized neighborhood vision mesh with severity-aware response.

- **Design:** [`docs/DESIGN.md`](docs/DESIGN.md)
- **Pitch:** [`docs/PITCH.md`](docs/PITCH.md)
- **Action router (Person 2):** [`action_router/README.md`](action_router/README.md)
- **Vision pipeline (Person 1):** [`vision_pipeline/README.md`](vision_pipeline/README.md) ← _this branch_

## Branches

| Branch | Owner | Scope |
|--------|-------|-------|
| `main` | shared | Design docs only |
| `vision-pipeline` | Amish | YOLO trigger + rolling buffer + Qwen2-VL classifier |
| `action-router` | friend | Receives event JSON → Claude + ElevenLabs + Twilio |

The two backend branches develop in parallel against a fixed event schema and merge into `main` at the end.

## Quick start (action router side)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # fill in API keys
python -m scripts.run_service           # FastAPI on :8001
# in another terminal:
python -m scripts.send_test_event --tier 3
```
