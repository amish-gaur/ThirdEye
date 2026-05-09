# ThirdEye / SafeWatch

Decentralized neighborhood vision mesh with severity-aware response.

- **Design:** [`docs/DESIGN.md`](docs/DESIGN.md)
- **Pitch:** [`docs/PITCH.md`](docs/PITCH.md)
- **Action router (Person 2):** [`action_router/README.md`](action_router/README.md)
- **Vision pipeline (Person 1):** [`vision_pipeline/README.md`](vision_pipeline/README.md)

## Vision ↔ action router (integration)

1. Start the router: `python -m scripts.run_service` (port **8001** by default).
2. Point the camera machine at the router with **`ACTION_ROUTER_URL`** in `.env`:
   - Same laptop: `http://127.0.0.1:8001/event`
   - Teammate / different network: your **`https://…ngrok…/event`** URL (router must be reachable).
3. Run vision: `python -m scripts.run_vision`

Test payloads from `send_test_event` use **fixtures** (e.g. “red hoodie”) — **not** the live model. Real descriptions come from **`scripts.run_vision`** posting classifier output.

## Branches

| Branch | Scope |
|--------|-------|
| `main` | Design docs |
| `action-router` | **Merged backend:** FastAPI router + vision pipeline (YOLO + Qwen); integrate here |

Development may still use separate topic branches; integration lands on **`action-router`** / **`main`**.

## Quick start (action router side)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # fill in API keys
python -m scripts.run_service           # FastAPI on :8001
# in another terminal:
python -m scripts.send_test_event --tier 3
```
