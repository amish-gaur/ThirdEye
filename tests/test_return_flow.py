"""Confidence-gated return flow: auto / ask / decline branching."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

import pytest

from action_router import package_identifier, return_flow
from action_router.amazon_return import ReturnResult
from action_router.config import Config
from action_router.disambiguate import _pending  # type: ignore[attr-defined]
from action_router.package_identifier import OrderCandidate, PackageMatch
from action_router.router import execute_action
from scripts._fixtures import sample_event


@pytest.fixture
def return_config(dry_config: Config, tmp_path: Path) -> Config:
    return replace(
        dry_config,
        return_flow_enabled=True,
        return_auto_threshold=0.85,
        return_ask_threshold=0.55,
        return_log_path=tmp_path / "return_log.jsonl",
        amazon_storage_state=tmp_path / "missing.json",
        amazon_dry_run=True,
    )


@pytest.fixture(autouse=True)
def _clear_pending_and_identifier():
    _pending.clear()
    original = package_identifier._active_identifier
    yield
    _pending.clear()
    package_identifier._active_identifier = original


def _stub_match(monkeypatch, match: PackageMatch) -> None:
    def fake(_clip, _event):
        return match
    package_identifier.set_identifier(fake)


def _stub_return(monkeypatch, ok: bool, error: Optional[str] = None) -> list[str]:
    """Stub Amazon return; record order_ids attempted. Returns the list."""
    attempts: list[str] = []

    def fake_init(order_id, *, incident_id, evidence_url=None, reason=None, config=None):
        attempts.append(order_id)
        return ReturnResult(
            ok=ok,
            order_id=order_id,
            return_id="RMA-TEST-1" if ok else None,
            dry_run=True,
            error=error,
            steps=["nav_orders", "nav_return_flow", "dry_run_stop"] if ok else ["nav_orders"],
        )

    monkeypatch.setattr(return_flow, "initiate_return", fake_init)
    return attempts


# ---- AUTO branch ---------------------------------------------------------


def test_auto_branch_high_confidence_files_return(
    return_config, monkeypatch, tmp_path
) -> None:
    _stub_match(
        monkeypatch,
        PackageMatch(
            order_id="123-AUTO",
            order_title="Sony WH-1000XM5",
            confidence=0.92,
            candidates=[OrderCandidate(order_id="123-AUTO", title="Sony WH-1000XM5", confidence=0.92)],
        ),
    )
    attempts = _stub_return(monkeypatch, ok=True)

    event = sample_event(tier=3, behavior_pattern="taking_item")
    event["incident_id"] = "inc_auto_1"

    result = execute_action(event, config=return_config)

    assert result.return_flow is not None
    assert result.return_flow.decision == "auto"
    assert attempts == ["123-AUTO"]
    assert "return_filed" in result.return_flow.actions
    assert "undo_sms_sent" in result.return_flow.actions
    # Log was written.
    log_path = tmp_path / "return_log.jsonl"
    assert log_path.exists()
    assert "auto" in log_path.read_text()


def test_auto_branch_failed_return_falls_back_to_evidence_sms(
    return_config, monkeypatch
) -> None:
    _stub_match(
        monkeypatch,
        PackageMatch(
            order_id="123-FAIL",
            order_title="thing",
            confidence=0.95,
            candidates=[OrderCandidate(order_id="123-FAIL", title="thing", confidence=0.95)],
        ),
    )
    _stub_return(monkeypatch, ok=False, error="auth_expired")

    event = sample_event(tier=3, behavior_pattern="taking_item")
    event["incident_id"] = "inc_auto_2"

    result = execute_action(event, config=return_config)

    assert result.return_flow.decision == "auto"
    assert "return_filed" not in result.return_flow.actions
    assert "evidence_sms_sent" in result.return_flow.actions
    assert any("auth_expired" in e for e in result.return_flow.errors)


# ---- ASK branch ----------------------------------------------------------


def test_ask_branch_mid_confidence_sends_candidates(
    return_config, monkeypatch
) -> None:
    candidates = [
        OrderCandidate(order_id="A", title="Headphones", confidence=0.7),
        OrderCandidate(order_id="B", title="Coffee maker", confidence=0.3),
    ]
    _stub_match(
        monkeypatch,
        PackageMatch(
            order_id="A",
            order_title="Headphones",
            confidence=0.7,
            candidates=candidates,
        ),
    )
    attempts = _stub_return(monkeypatch, ok=True)

    event = sample_event(tier=3, behavior_pattern="taking_item")
    event["incident_id"] = "inc_ask_1"

    result = execute_action(event, config=return_config)

    assert result.return_flow.decision == "ask"
    assert "ask_sms_sent" in result.return_flow.actions
    assert attempts == []  # no return fired yet — we're waiting on the homeowner
    pending = _pending.get("inc_ask_1")
    assert pending is not None and pending.kind == "ask"
    assert [c.order_id for c in pending.candidates] == ["A", "B"]


# ---- DECLINE branch ------------------------------------------------------


def test_decline_branch_low_confidence_evidence_only(
    return_config, monkeypatch
) -> None:
    _stub_match(monkeypatch, PackageMatch.empty("nothing matched"))
    attempts = _stub_return(monkeypatch, ok=True)

    event = sample_event(tier=3, behavior_pattern="taking_item")
    event["incident_id"] = "inc_decline_1"

    result = execute_action(event, config=return_config)

    assert result.return_flow.decision == "decline"
    assert "evidence_sms_sent" in result.return_flow.actions
    assert attempts == []


# ---- behavior gate -------------------------------------------------------


def test_collapsed_pattern_does_not_run_return_flow(
    return_config, monkeypatch
) -> None:
    _stub_match(
        monkeypatch,
        PackageMatch(
            order_id="X",
            order_title="anything",
            confidence=0.99,
            candidates=[OrderCandidate(order_id="X", title="anything", confidence=0.99)],
        ),
    )
    attempts = _stub_return(monkeypatch, ok=True)

    event = sample_event(tier=4, behavior_pattern="collapsed")

    result = execute_action(event, config=return_config)

    assert result.return_flow is None
    assert any("return_flow_skipped_pattern" in a for a in result.actions)
    assert attempts == []


# ---- reply parsing -------------------------------------------------------


def test_parse_ask_reply_picks_correct_order() -> None:
    from action_router.disambiguate import parse_ask_reply

    candidates = [
        OrderCandidate(order_id="A", title="x", confidence=0.5),
        OrderCandidate(order_id="B", title="y", confidence=0.4),
    ]
    assert parse_ask_reply("1", candidates) == "A"
    assert parse_ask_reply("2", candidates) == "B"
    assert parse_ask_reply("3", candidates) is None
    assert parse_ask_reply("N", candidates) is None
    assert parse_ask_reply("none", candidates) is None
    assert parse_ask_reply("", candidates) is None


def test_is_stop_reply() -> None:
    from action_router.disambiguate import is_stop_reply

    assert is_stop_reply("STOP")
    assert is_stop_reply("stop")
    assert is_stop_reply("Cancel")
    assert is_stop_reply("UNDO")
    assert not is_stop_reply("1")
    assert not is_stop_reply("yes")
