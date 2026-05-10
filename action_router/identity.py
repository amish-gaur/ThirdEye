"""Phone-driven identity sessions.

Flow:
  1. iPhone collects {name, email}, POSTs `/api/identity` → backend
     returns a 6-digit `code` plus a `session_id` (uuid).
  2. Phone shows the code on screen ("Open the ThirdEye web app and type
     this code"). While the user is reading it, the action router is
     already warm (vision pipeline started with `make run`).
  3. Web user types the code → POSTs `/api/identity/by-code/{code}/claim`.
     The session flips to `claimed`; web stores the identity in localStorage
     and renders "Logged in as <name>".
  4. Either side can poll `GET /api/identity/by-code/{code}` to track state.

Storage is in-process. That's intentional: the demo runs as a single
brain laptop, sessions cap at 16 concurrent, and a router restart is the
right time to drop them. Sessions auto-expire after 10 minutes of no
activity so the code space stays clean.
"""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger("action_router.identity")

CODE_TTL_SECONDS = 10 * 60
MAX_SESSIONS = 16


@dataclass
class IdentitySession:
    session_id: str
    code: str
    name: str
    email: str
    device_id: Optional[str]
    created_at: float
    claimed_at: Optional[float] = None
    last_seen: float = field(default_factory=time.time)

    @property
    def status(self) -> str:
        return "claimed" if self.claimed_at is not None else "pending"

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_seen) > CODE_TTL_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "code": self.code,
            "name": self.name,
            "email": self.email,
            "device_id": self.device_id,
            "status": self.status,
            "created_at": self.created_at,
            "claimed_at": self.claimed_at,
        }


class IdentityStore:
    """Thread-safe in-memory store of pending + claimed identity sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_code: Dict[str, IdentitySession] = {}
        self._by_session: Dict[str, IdentitySession] = {}

    def submit(
        self, *, name: str, email: str, device_id: Optional[str] = None
    ) -> IdentitySession:
        if not name.strip() or not email.strip():
            raise ValueError("name and email required")
        with self._lock:
            self._reap_locked()
            if len(self._by_code) >= MAX_SESSIONS:
                # Evict the oldest so a phone restart never gets stuck.
                oldest = min(self._by_code.values(), key=lambda s: s.last_seen)
                self._by_code.pop(oldest.code, None)
                self._by_session.pop(oldest.session_id, None)
            code = self._mint_code_locked()
            session = IdentitySession(
                session_id=uuid.uuid4().hex,
                code=code,
                name=name.strip()[:80],
                email=email.strip()[:120],
                device_id=(device_id or "").strip()[:120] or None,
                created_at=time.time(),
            )
            self._by_code[code] = session
            self._by_session[session.session_id] = session
            log.info(
                "identity submitted code=%s name=%r email=%r device=%r",
                code,
                session.name,
                session.email,
                session.device_id,
            )
            return session

    def get_by_code(self, code: str) -> Optional[IdentitySession]:
        with self._lock:
            self._reap_locked()
            session = self._by_code.get(code.strip().upper())
            if session is not None:
                session.last_seen = time.time()
            return session

    def claim(self, code: str) -> Optional[IdentitySession]:
        with self._lock:
            self._reap_locked()
            session = self._by_code.get(code.strip().upper())
            if session is None:
                return None
            if session.claimed_at is None:
                session.claimed_at = time.time()
            session.last_seen = time.time()
            log.info("identity claimed code=%s name=%r", session.code, session.name)
            return session

    def list_active(self) -> list[IdentitySession]:
        with self._lock:
            self._reap_locked()
            return list(self._by_code.values())

    # -- internal ----------------------------------------------------------

    def _mint_code_locked(self) -> str:
        # 6-digit alphanumeric, ambiguous chars stripped (no O/0, I/1, L).
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
        for _ in range(64):
            code = "".join(random.choice(alphabet) for _ in range(6))
            if code not in self._by_code:
                return code
        # Pathological collision after 64 tries — fall through with uuid prefix.
        return uuid.uuid4().hex[:6].upper()

    def _reap_locked(self) -> None:
        now = time.time()
        stale = [c for c, s in self._by_code.items() if (now - s.last_seen) > CODE_TTL_SECONDS]
        for c in stale:
            session = self._by_code.pop(c, None)
            if session is not None:
                self._by_session.pop(session.session_id, None)
                log.debug("identity reaped code=%s", c)


_singleton: Optional[IdentityStore] = None
_singleton_lock = threading.Lock()


def get_identity_store() -> IdentityStore:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = IdentityStore()
        return _singleton
