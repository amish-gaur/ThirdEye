"""Pending disambiguation store + SMS copy for the human-in-the-loop path.

When the identifier's confidence falls in the ASK band, we text the
homeowner up to 3 candidate orders and stash a `PendingDecision` keyed by
incident_id. An inbound SMS webhook (`/sms/inbound` in service.py) parses
the reply digit and resolves the pending decision into a concrete order.

Same store is used for the post-auto-return UNDO window: after every
auto-return we register a pending decision with kind="undo"; if the
homeowner texts STOP before it expires, the router cancels the return.

In-process dict for now. If we ever scale beyond one router instance,
swap in Redis without touching callers.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import CONFIG, Config
from .messaging import SmsResult, send_sms
from .package_identifier import OrderCandidate

log = logging.getLogger("action_router.disambiguate")


@dataclass
class PendingDecision:
    incident_id: str
    kind: str  # "ask" or "undo"
    candidates: List[OrderCandidate] = field(default_factory=list)
    auto_order_id: Optional[str] = None  # set for "undo" kind
    expires_at: float = 0.0
    resolved: bool = False
    resolution: Optional[str] = None  # "picked:<order_id>", "stop", "expired", "ignored"


_pending: Dict[str, PendingDecision] = {}
_lock = threading.Lock()


def remember(decision: PendingDecision) -> None:
    with _lock:
        _pending[decision.incident_id] = decision


def get(incident_id: str) -> Optional[PendingDecision]:
    with _lock:
        return _pending.get(incident_id)


def resolve(incident_id: str, resolution: str) -> Optional[PendingDecision]:
    with _lock:
        d = _pending.get(incident_id)
        if d is None or d.resolved:
            return d
        d.resolved = True
        d.resolution = resolution
        return d


def latest_pending_of(kind: str) -> Optional[PendingDecision]:
    """Return the freshest unresolved pending decision of the given kind.

    Inbound SMS webhooks don't carry incident_id, only the homeowner's
    phone number. We assume one homeowner and resolve against the most
    recently-issued pending decision.
    """
    now = time.time()
    with _lock:
        candidates = [
            d
            for d in _pending.values()
            if d.kind == kind and not d.resolved and d.expires_at > now
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: d.expires_at, reverse=True)
    return candidates[0]


# ---- SMS copy ----------------------------------------------------------


def send_ask_sms(
    incident_id: str,
    candidates: List[OrderCandidate],
    *,
    clip_url: Optional[str] = None,
    config: Optional[Config] = None,
    ttl_seconds: int = 600,
) -> Optional[SmsResult]:
    """Text the homeowner up to 3 candidate orders. Records a PendingDecision.

    Reply parser later expects digits 1..N matching the order in this list.
    """
    cfg = config or CONFIG
    if not cfg.homeowner_phone:
        log.warning("ASK path skipped: HOMEOWNER_PHONE not configured")
        return None
    top = candidates[:3]
    if not top:
        return None
    lines = [
        "SafeWatch detected a possible package theft.",
        "Which order was it? Reply with the number, or N if none.",
    ]
    for i, c in enumerate(top, start=1):
        lines.append(f"{i}) {c.title}")
    body = "\n".join(lines)
    media = [clip_url] if clip_url else None
    sms = send_sms(cfg.homeowner_phone, body, media_urls=media, config=cfg)
    remember(
        PendingDecision(
            incident_id=incident_id,
            kind="ask",
            candidates=top,
            expires_at=time.time() + ttl_seconds,
        )
    )
    return sms


def send_undo_sms(
    incident_id: str,
    *,
    order_title: str,
    config: Optional[Config] = None,
) -> Optional[SmsResult]:
    """Inform homeowner an auto-return was filed and offer a STOP undo window."""
    cfg = config or CONFIG
    if not cfg.homeowner_phone:
        return None
    window = cfg.return_undo_window_seconds
    body = (
        f"SafeWatch filed an Amazon return for {order_title}. "
        f"Reply STOP within {window}s to cancel."
    )
    sms = send_sms(cfg.homeowner_phone, body, config=cfg)
    remember(
        PendingDecision(
            incident_id=incident_id,
            kind="undo",
            auto_order_id=None,  # populated by caller via remember if needed
            expires_at=time.time() + window,
        )
    )
    return sms


def send_evidence_only_sms(
    *,
    summary: str,
    clip_url: Optional[str] = None,
    config: Optional[Config] = None,
) -> Optional[SmsResult]:
    """Below-ASK confidence: tell the homeowner, send the clip, don't guess."""
    cfg = config or CONFIG
    if not cfg.homeowner_phone:
        return None
    body = f"SafeWatch: {summary} — couldn't match an order automatically."
    media = [clip_url] if clip_url else None
    return send_sms(cfg.homeowner_phone, body, media_urls=media, config=cfg)


# ---- Reply parsing -----------------------------------------------------


def parse_ask_reply(body: str, candidates: List[OrderCandidate]) -> Optional[str]:
    """Map an SMS body to a candidate's order_id, or None for explicit decline.

    Accepts: "1", "2", "3", "N", "no", "none". Anything else returns None
    (caller treats as ignored).
    """
    text = (body or "").strip().lower()
    if not text:
        return None
    if text in {"n", "no", "none"}:
        return None
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx].order_id
    return None


def is_stop_reply(body: str) -> bool:
    return (body or "").strip().lower() in {"stop", "cancel", "undo"}
