"""Voice call-state machine.

Shared by the inbound-voice service (this lane) and the outbound voice agent
(Rishab's lane). Tracks every active call leg per incident and resolves the
"first-to-acknowledge wins" race so we never double-handle an incident or
strand a leg.

Public surface:
    store    — Redis-backed state operations (atomic where it matters)
    cache    — active-incident cache populated by the action-router hook
    models   — pydantic shapes for the HTTP API
    api      — FastAPI router for cross-lane coordination
"""

from . import api, cache, models, store

__all__ = ["api", "cache", "models", "store"]
