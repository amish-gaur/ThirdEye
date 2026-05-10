"""Identifier seam: maps a stolen-package clip to an Amazon order.

This module defines the contract the rest of the return flow consumes.
The real implementation (codev) plugs into `identify_package` and returns
a `PackageMatch` with confidence and ranked candidates. The router uses
that confidence to choose between auto-return, ask-the-homeowner, and
evidence-only paths.

Until the real identifier lands, `identify_package` returns a stub match
governed by `IDENTIFIER_STUB_*` env vars so the rest of the pipeline can
be exercised end-to-end.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("action_router.package_identifier")


@dataclass
class OrderCandidate:
    order_id: str
    title: str
    confidence: float
    thumbnail_url: Optional[str] = None
    delivered_at: Optional[str] = None  # ISO 8601 string

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "title": self.title,
            "confidence": round(self.confidence, 3),
            "thumbnail_url": self.thumbnail_url,
            "delivered_at": self.delivered_at,
        }


@dataclass
class PackageMatch:
    """The identifier's verdict for a single stolen-package event.

    `confidence` is the model's belief that `order_id` is the right match.
    `candidates` is the ranked list including the top pick at index 0;
    used for SMS disambiguation when confidence is in the ask range.
    `reasoning` is human-readable, written into the return log.
    """

    order_id: Optional[str]
    order_title: Optional[str]
    confidence: float
    candidates: List[OrderCandidate] = field(default_factory=list)
    reasoning: str = ""

    @classmethod
    def empty(cls, reasoning: str = "no candidates") -> "PackageMatch":
        return cls(order_id=None, order_title=None, confidence=0.0, reasoning=reasoning)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_title": self.order_title,
            "confidence": round(self.confidence, 3),
            "candidates": [c.to_dict() for c in self.candidates],
            "reasoning": self.reasoning,
        }


# Identifier strategy: a callable so codev can swap in the real one without
# touching the router. See `set_identifier()` for runtime injection.
IdentifyFn = Callable[[Optional[str], Dict[str, Any]], PackageMatch]


def _stub_identifier(clip_path: Optional[str], event: Dict[str, Any]) -> PackageMatch:
    """Test-only identifier driven by env vars. Lets us exercise auto/ask/decline.

    IDENTIFIER_STUB_CONFIDENCE  - float in [0, 1]
    IDENTIFIER_STUB_ORDER_ID    - top-pick order id
    IDENTIFIER_STUB_ORDER_TITLE - human-readable title
    """
    _ = clip_path, event
    try:
        confidence = float(os.getenv("IDENTIFIER_STUB_CONFIDENCE", "0.0"))
    except ValueError:
        confidence = 0.0
    order_id = os.getenv("IDENTIFIER_STUB_ORDER_ID") or None
    order_title = os.getenv("IDENTIFIER_STUB_ORDER_TITLE") or None
    if not order_id or confidence <= 0:
        return PackageMatch.empty("stub identifier: no order configured")
    candidates = [
        OrderCandidate(
            order_id=order_id, title=order_title or order_id, confidence=confidence
        )
    ]
    return PackageMatch(
        order_id=order_id,
        order_title=order_title,
        confidence=confidence,
        candidates=candidates,
        reasoning="stub identifier (env-driven)",
    )


_active_identifier: IdentifyFn = _stub_identifier


def set_identifier(fn: IdentifyFn) -> None:
    """Inject a real identifier. Call once at app startup from codev's module."""
    global _active_identifier
    _active_identifier = fn
    log.info("package_identifier swapped to %s", fn)


def identify_package(clip_path: Optional[str], event: Dict[str, Any]) -> PackageMatch:
    """Public entry point. Routes through the active identifier."""
    try:
        return _active_identifier(clip_path, event)
    except Exception as exc:
        log.exception("identifier raised; treating as no-match: %s", exc)
        return PackageMatch.empty(f"identifier error: {exc}")
