# Lane: Live querying (branch `lane/live-query`)

> **You are on branch `lane/live-query`.** Build only what's described here. Three sibling branches (`lane/phone-infra`, `lane/mobile-ux`, `lane/connection-mesh`) are running in parallel — respect file boundaries below or you will collide at merge.
>
> Read `docs/PLAN_ADITYA.md` Lane 1 first. This file is the branch-scoped contract.

---

## Mission

Build the natural-language Q&A backend over event history and live feed:
- **Historical:** "Show me anyone in a hooded jacket last night."
- **Live:** "What's on the front porch right now?"
- Multi-turn ("zoom in on the third one"), streaming responses, cited clips.

This branch ships the **API and data layer**. The mobile/web *chat surface* is built in `lane/mobile-ux` against the contracts you publish here.

---

## Files this branch OWNS

- `services/__init__.py` (create if absent)
- `services/_shared/` — minimal shared scaffolding (auth middleware, mongo client, R2 client). Other lanes will reuse; design it conservatively. Files: `auth.py`, `mongo.py`, `r2.py`, `clerk.py`.
- `services/query/` — entire subtree (FastAPI subapp, Claude retrieval planner, Atlas Vector wrapper, SSE streamer)
- `services/events_store/` — Mongo schemas, ingestion writer, CLIP embedding worker
- One surgical hook in `action_router/router.py` — see "Hook contract" below.
- `requirements.txt` — add: `pymongo`, `motor`, `open_clip_torch`, `boto3` (for R2), `sse-starlette`
- Tests under `tests/services/query/` and `tests/services/events_store/`

## Files this branch DOES NOT TOUCH

- `vision_pipeline/` — Amish's territory.
- `action_router/` outside the one designated hook.
- `apps/`, `packages/` — `lane/mobile-ux`'s territory.
- `infra/` — `lane/connection-mesh`'s territory.
- `services/inbound_voice/`, `services/voice_state/`, `services/pairing/`, `services/signaling/` — other lanes.

## Hook contract (the only edit to `action_router/`)

Append to `execute_action()` in `action_router/router.py`, just before the final return:

```python
try:
    from services.events_store.ingest import record_event
    record_event(event_json, result.to_dict())
except Exception:
    log.exception("events store ingest failed (non-fatal)")
```

`record_event` MUST be best-effort — the action router never fails because of us.

## Contracts this lane PUBLISHES

- **HTTP API** mounted at `/query` and `/events`:
  - `POST /query` — `{question, conversation_id?, scope: "history"|"live"|"auto"}` → SSE stream
  - `GET /query/conversations/{id}` — full transcript with cited clips
  - `GET /events/{id}` — single event detail
  - `GET /events/{id}/clip` — signed R2 URL for the clip
  - `GET /events?filters...` — paginated listing for the mobile timeline
- **Pydantic models** at `services/query/models.py` and `services/events_store/schema.py`
- **TS type export** at `services/query/_generated/query.ts` and `services/events_store/_generated/events.ts` (run a small script in this branch's `Makefile` that generates these from the pydantic models — `lane/mobile-ux` imports them)

## Contracts this lane CONSUMES

- **Clerk JWT** — you build the verifier in `services/_shared/auth.py`. Env: `CLERK_JWKS_URL`, `CLERK_ISSUER`.
- **R2 credentials** — env: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
- **LiveKit view tokens** for live-scope queries — `lane/connection-mesh` will provide `services/signaling/livekit.py:mint_view_token(node_id)`. **STUB if missing:** live-scope returns 503 "live not available" until that lands.

## Sequencing within this branch

1. `services/_shared/{auth,mongo,r2,clerk}.py` scaffolding.
2. `services/events_store/schema.py` + ingestion writer + the action-router hook.
3. CLIP embedding worker — separate process, queue-based (use Mongo as the queue to avoid adding another infra dep).
4. `POST /query` with structured filters only (no semantic yet).
5. Atlas Vector index + semantic retrieval.
6. Claude retrieval planner (NL → filter+vector plan, low temp, cached by hash).
7. SSE streaming + multi-turn conversation memory.
8. Live scope: pull current frame via LiveKit view token, send to Qwen.
9. TS type export script.

## Definition of done for this branch

- All endpoints work with Clerk auth in place.
- Atlas Vector index populated for every event with a clip.
- p50 < 1.2s to first token, < 2.5s to first cited clip on the demo dataset.
- Tests cover structured filter, semantic, multi-turn, auth gating.
- One end-to-end integration test using Mongo + Redis testcontainers.
- TS types generated and committed.
- No edits outside the OWNED list above.

## Merge checklist

- [ ] No changes to `vision_pipeline/`, `apps/`, `packages/`, `infra/`.
- [ ] `action_router/router.py` diff is the single hook block, nothing else.
- [ ] `requirements.txt` only adds — never removes.
- [ ] All new endpoints behind `/query` or `/events`.
- [ ] CI green.
