"""Vision-based package identifier.

Replaces the env-var stub. Pipeline:

1. Pull a representative frame from the theft clip.
2. Ask Claude to describe what was taken (size, color, box vs envelope, brand
   stickers if visible).
3. Score that description against each order in the cached orders JSON
   (`amazon_orders.json`, refreshed by scripts/refresh_amazon_orders.py).
4. Return a `PackageMatch` with order_id, asin, ranked candidates, confidence.

If the orders cache is empty/missing or vision fails, returns
`PackageMatch.empty(...)` — the router falls back to evidence-only SMS.

Confidence calibration:
- >= 0.85: top match clearly dominant (>2x next, vision description is
  specific). Auto-return.
- 0.55 - 0.85: a likely candidate but real ambiguity. Ask homeowner via SMS.
- < 0.55: nothing convincing. Decline.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import CONFIG
from .package_identifier import OrderCandidate, PackageMatch, set_identifier

log = logging.getLogger("action_router.claude_identifier")

VISION_MODEL = "claude-sonnet-4-5"
MATCH_MODEL = "claude-sonnet-4-5"

DESCRIBE_PROMPT = """A package was stolen from a porch. Describe the package being taken in this frame in 1-3 sentences.
Focus on: approximate size (small/medium/large), shape (box/envelope/padded mailer/tube), color, any visible
branding or labels (Amazon smile, USPS, FedEx, etc.), and anything distinctive (e.g. "long thin box, Apple-style").
Do not describe the person or the surroundings — just the package."""

MATCH_PROMPT = """You are matching a stolen package to one of the recent Amazon orders.

Stolen-package description (from CCTV):
{description}

Recent Amazon orders (JSON):
{orders_json}

Return JSON:
{{
  "best_order_id": "<order id or null>",
  "best_asin": "<asin or null>",
  "best_title": "<title or null>",
  "confidence": <float 0-1>,
  "reasoning": "<one sentence>",
  "ranked": [
    {{"order_id": "...", "asin": "...", "title": "...", "score": <0-1>}},
    ...
  ]
}}

Confidence rubric:
- 0.9+: description specifically matches one order's item shape/size and clearly does not match others.
- 0.6-0.85: plausible match but multiple orders could fit, OR description is vague.
- 0.3-0.55: weak match.
- < 0.3: no order plausibly matches; return null for best_*.

Return ONLY the JSON object. No prose, no code fences."""


def _load_orders(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        log.exception("failed to read orders cache %s", path)
        return []


def _frame_b64_from_clip(clip_path: str) -> Optional[str]:
    """Grab a frame ~1/3 into the clip (likely shows the package mid-grab)."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    cap = cv2.VideoCapture(clip_path)
    if not cap.isOpened():
        return None
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target = max(0, total // 3)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode()
    finally:
        cap.release()


def _describe_package(client, frame_b64: Optional[str], event: Dict[str, Any]) -> Optional[str]:
    """Vision call. Falls back to event summary if no frame is available."""
    summary = str(event.get("one_line_summary") or "").strip()
    if not frame_b64:
        # No clip — best we can do is reuse the vision-pipeline summary.
        return summary or None

    content: List[Dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame_b64}},
        {"type": "text", "text": DESCRIBE_PROMPT},
    ]
    if summary:
        content.append({"type": "text", "text": f"Vision-pipeline summary for context: {summary}"})

    resp = client.messages.create(
        model=VISION_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    return text or summary or None


def _match_against_orders(
    client, description: str, orders: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    prompt = MATCH_PROMPT.format(
        description=description,
        orders_json=json.dumps(orders, indent=2)[:60_000],
    )
    resp = client.messages.create(
        model=MATCH_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("matcher returned non-JSON: %s", raw[:300])
        return None, []
    ranked = parsed.get("ranked") if isinstance(parsed.get("ranked"), list) else []
    return parsed, ranked


def claude_identify(clip_path: Optional[str], event: Dict[str, Any]) -> PackageMatch:
    """Identifier impl. Plug in via set_identifier(claude_identify)."""
    try:
        import anthropic
    except ImportError:
        return PackageMatch.empty("anthropic SDK not installed")

    orders = _load_orders(Path(CONFIG.amazon_orders_cache))
    if not orders:
        return PackageMatch.empty(
            "orders cache empty — run scripts/refresh_amazon_orders.py"
        )

    client = anthropic.Anthropic()

    frame_b64 = _frame_b64_from_clip(clip_path) if clip_path and os.path.exists(clip_path) else None
    description = _describe_package(client, frame_b64, event)
    if not description:
        return PackageMatch.empty("no description (no clip + no summary)")

    parsed, ranked = _match_against_orders(client, description, orders)
    if not parsed:
        return PackageMatch.empty("matcher returned unparseable response")

    confidence = float(parsed.get("confidence") or 0.0)
    best_id = parsed.get("best_order_id")
    best_asin = parsed.get("best_asin")
    best_title = parsed.get("best_title")
    reasoning = parsed.get("reasoning") or "claude_identifier"

    candidates: List[OrderCandidate] = []
    for r in ranked[:5]:
        if not isinstance(r, dict):
            continue
        oid = r.get("order_id")
        if not oid:
            continue
        candidates.append(
            OrderCandidate(
                order_id=str(oid),
                title=str(r.get("title") or oid),
                confidence=float(r.get("score") or 0.0),
                asin=str(r["asin"]) if r.get("asin") else None,
            )
        )

    if not best_id:
        return PackageMatch(
            order_id=None,
            order_title=None,
            confidence=confidence,
            asin=None,
            candidates=candidates,
            reasoning=f"no plausible match: {reasoning}",
        )

    return PackageMatch(
        order_id=str(best_id),
        order_title=str(best_title) if best_title else None,
        confidence=confidence,
        asin=str(best_asin) if best_asin else None,
        candidates=candidates,
        reasoning=f"vision: {description[:160]} | match: {reasoning}",
    )


def install() -> None:
    """Activate the Claude identifier. Call once at app startup."""
    set_identifier(claude_identify)
    log.info("claude_identifier installed")
