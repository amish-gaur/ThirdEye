"""Confidence-gated return dispatcher.

After tier >= 3 fires its existing notification path, the router calls
`maybe_initiate_return(event)`. We:

1. Ask the package identifier for a match.
2. Branch on confidence:
   - >= return_auto_threshold        : auto-return + UNDO SMS
   - >= return_ask_threshold         : ASK SMS with candidates
   - otherwise                       : evidence-only SMS, no action
3. Append a JSONL entry for every decision.

This module is intentionally thin — it composes other modules so each
piece (identifier, browser, SMS) stays independently testable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import return_log
from .amazon_return import ReturnResult, initiate_return
from .config import CONFIG, Config
from .disambiguate import (
    PendingDecision,
    remember,
    send_ask_sms,
    send_evidence_only_sms,
    send_undo_sms,
)
from .package_identifier import PackageMatch, identify_package

log = logging.getLogger("action_router.return_flow")


@dataclass
class ReturnFlowResult:
    decision: str  # "auto", "ask", "decline", "skip"
    match: Optional[PackageMatch] = None
    return_result: Optional[ReturnResult] = None
    actions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "match": self.match.to_dict() if self.match else None,
            "return_result": _return_result_dict(self.return_result),
            "actions": self.actions,
            "errors": self.errors,
        }


def _return_result_dict(r: Optional[ReturnResult]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "ok": r.ok,
        "order_id": r.order_id,
        "return_id": r.return_id,
        "dry_run": r.dry_run,
        "error": r.error,
        "steps": r.steps,
    }


def maybe_initiate_return(
    event: Dict[str, Any], config: Optional[Config] = None
) -> ReturnFlowResult:
    cfg = config or CONFIG
    res = ReturnFlowResult(decision="skip")

    if not cfg.return_flow_enabled:
        res.actions.append("return_flow_disabled")
        return res

    incident_id = str(event.get("incident_id") or "").strip()
    if not incident_id:
        res.actions.append("missing_incident_id")
        return res

    clip_filename = event.get("clip_filename")
    clip_url = cfg.media_url(clip_filename) if clip_filename else None
    clip_path = event.get("clip_path")

    match = identify_package(clip_path, event)
    res.match = match
    log.info(
        "identifier match incident=%s order=%s confidence=%.2f reason=%r",
        incident_id,
        match.order_id,
        match.confidence,
        match.reasoning,
    )

    log_base = {
        "incident_id": incident_id,
        "tier": event.get("tier"),
        "summary": event.get("one_line_summary"),
        "clip_url": clip_url,
        "match": match.to_dict(),
    }

    # AUTO branch
    if match.order_id and match.confidence >= cfg.return_auto_threshold:
        res.decision = "auto"
        return_result = initiate_return(
            match.order_id,
            incident_id=incident_id,
            evidence_url=clip_url,
            config=cfg,
        )
        res.return_result = return_result
        res.actions.append("return_attempted")
        if return_result.ok:
            res.actions.append("return_filed")
            sms = send_undo_sms(
                incident_id,
                order_title=match.order_title or match.order_id,
                config=cfg,
            )
            if sms is not None:
                res.actions.append("undo_sms_sent")
                # The undo store needs to know which order to cancel.
                remember(
                    PendingDecision(
                        incident_id=incident_id,
                        kind="undo",
                        auto_order_id=match.order_id,
                        expires_at=time.time() + cfg.return_undo_window_seconds,
                    )
                )
        else:
            res.errors.append(f"return_failed: {return_result.error}")
            # Auto attempt failed (e.g. auth_expired) — don't leave the
            # homeowner in the dark.
            send_evidence_only_sms(
                summary=str(event.get("one_line_summary") or "package theft detected"),
                clip_url=clip_url,
                config=cfg,
            )
            res.actions.append("evidence_sms_sent")

        return_log.append({**log_base, "decision": "auto", **(_return_result_dict(return_result) or {})}, config=cfg)
        return res

    # ASK branch
    if match.candidates and match.confidence >= cfg.return_ask_threshold:
        res.decision = "ask"
        sms = send_ask_sms(
            incident_id,
            match.candidates,
            clip_url=clip_url,
            config=cfg,
        )
        if sms is not None:
            res.actions.append("ask_sms_sent")
        else:
            res.errors.append("ask_sms_skipped")
        return_log.append({**log_base, "decision": "ask"}, config=cfg)
        return res

    # DECLINE branch
    res.decision = "decline"
    sms = send_evidence_only_sms(
        summary=str(event.get("one_line_summary") or "package theft detected"),
        clip_url=clip_url,
        config=cfg,
    )
    if sms is not None:
        res.actions.append("evidence_sms_sent")
    return_log.append({**log_base, "decision": "decline"}, config=cfg)
    return res
