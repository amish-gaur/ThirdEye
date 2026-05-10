"""Thread-safe frame store + per-token pairing state.

Each phone that connects gets its own slot keyed by token. The slot tracks
the latest JPEG bytes, when the phone first connected, when the most recent
frame arrived, and a list of asyncio queues that MJPEG streamers subscribe
to so they get notified the instant a new frame lands.

This module deliberately stays framework-free so it can be used from both
the FastAPI request handlers and from background tasks/tests.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


def new_token(prefix: str = "") -> str:
    """Generate an unguessable but human-friendly pairing token."""
    body = secrets.token_urlsafe(6)
    return f"{prefix}{body}" if prefix else body


@dataclass
class PhoneSlot:
    """In-memory state for a single paired phone."""

    token: str
    created_at: float = field(default_factory=time.time)
    first_frame_at: Optional[float] = None
    last_frame_at: Optional[float] = None
    frame_count: int = 0
    latest_jpeg: Optional[bytes] = None
    label: Optional[str] = None  # human label set from the phone (e.g. "Sumedh's iPhone")
    width: int = 0
    height: int = 0
    # asyncio.Queue subscribers used by MJPEG/sse fan-out. Each queue receives
    # the raw JPEG bytes as soon as a new frame arrives. Bounded length so a
    # slow reader can't pin memory.
    _subscribers: list[asyncio.Queue[bytes]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def is_live(self, *, max_age_seconds: float = 5.0) -> bool:
        """True when a frame arrived recently (default: within 5s)."""
        if self.last_frame_at is None:
            return False
        return (time.time() - self.last_frame_at) <= max_age_seconds

    def is_live_within(self, max_age_seconds: float) -> bool:
        if self.last_frame_at is None:
            return False
        return (time.time() - self.last_frame_at) <= max_age_seconds

    def status(self) -> dict:
        return {
            "token": self.token,
            "label": self.label,
            "connected": self.first_frame_at is not None,
            "live": self.is_live_within(5.0),
            "first_frame_at": self.first_frame_at,
            "last_frame_at": self.last_frame_at,
            "frame_count": self.frame_count,
            "width": self.width,
            "height": self.height,
            "age_seconds": (
                time.time() - self.last_frame_at if self.last_frame_at else None
            ),
        }


class FrameStore:
    """Thread-safe registry of paired phones keyed by token."""

    def __init__(self, *, default_token: str = "default") -> None:
        self._slots: dict[str, PhoneSlot] = {}
        self._lock = threading.Lock()
        self.default_token = default_token
        # Always provision the default slot so the QR/pair page can render
        # immediately without anyone connecting first.
        self.ensure_slot(default_token)

    # --- registry ------------------------------------------------------

    def ensure_slot(self, token: str, *, label: Optional[str] = None) -> PhoneSlot:
        with self._lock:
            slot = self._slots.get(token)
            if slot is None:
                slot = PhoneSlot(token=token, label=label)
                self._slots[token] = slot
            elif label and not slot.label:
                slot.label = label
            return slot

    def get(self, token: str) -> Optional[PhoneSlot]:
        with self._lock:
            return self._slots.get(token)

    def list_tokens(self) -> list[str]:
        with self._lock:
            return list(self._slots.keys())

    def all_status(self) -> list[dict]:
        with self._lock:
            return [slot.status() for slot in self._slots.values()]

    # --- ingest --------------------------------------------------------

    def publish_frame(
        self,
        token: str,
        jpeg_bytes: bytes,
        *,
        width: int = 0,
        height: int = 0,
        label: Optional[str] = None,
    ) -> PhoneSlot:
        """Store a new JPEG frame and wake any subscribers."""
        slot = self.ensure_slot(token, label=label)
        now = time.time()
        with slot._lock:
            if slot.first_frame_at is None:
                slot.first_frame_at = now
            slot.last_frame_at = now
            slot.frame_count += 1
            slot.latest_jpeg = jpeg_bytes
            if width:
                slot.width = width
            if height:
                slot.height = height
            if label:
                slot.label = label
            subs = list(slot._subscribers)
        for q in subs:
            try:
                q.put_nowait(jpeg_bytes)
            except asyncio.QueueFull:
                # drop oldest, push newest — MJPEG viewers prefer "live" over "complete"
                try:
                    _ = q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(jpeg_bytes)
                except Exception:
                    pass
        return slot

    # --- subscribers (MJPEG / SSE fan-out) -----------------------------

    def subscribe(self, token: str) -> asyncio.Queue[bytes]:
        slot = self.ensure_slot(token)
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        with slot._lock:
            slot._subscribers.append(q)
            # Prime with whatever we already have so a freshly-attached MJPEG
            # consumer doesn't see a blank screen until the next frame.
            if slot.latest_jpeg is not None:
                try:
                    q.put_nowait(slot.latest_jpeg)
                except asyncio.QueueFull:
                    pass
        return q

    def unsubscribe(self, token: str, q: asyncio.Queue[bytes]) -> None:
        slot = self.get(token)
        if slot is None:
            return
        with slot._lock:
            if q in slot._subscribers:
                slot._subscribers.remove(q)


_GLOBAL_STORE: Optional[FrameStore] = None


def get_frame_store() -> FrameStore:
    """Module-level singleton used by the FastAPI handlers."""
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        _GLOBAL_STORE = FrameStore()
    return _GLOBAL_STORE


def reset_frame_store_for_tests() -> None:
    """Reset the singleton between tests."""
    global _GLOBAL_STORE
    _GLOBAL_STORE = None
