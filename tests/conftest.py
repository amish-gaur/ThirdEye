"""Shared pytest fixtures.

IMPORTANT: this file must run BEFORE any `action_router.*` module is imported
so that we can force safe defaults into the environment. We set DRY_RUN and
clear API credentials so tests can never make real Twilio / Claude / ElevenLabs
calls, even if the developer has a populated `.env` on disk.
"""

from __future__ import annotations

import os

# --- env hardening: must happen before action_router.* imports ---
os.environ["DRY_RUN"] = "true"
os.environ["USE_CLAUDE"] = "false"
os.environ["USE_ELEVENLABS"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["TWILIO_FROM_NUMBER"] = "+15555550100"
os.environ["HOMEOWNER_PHONE"] = "+15555550101"
os.environ["EMERGENCY_DISPATCH_PHONE"] = "+15555550102"
os.environ["FAMILY_PHONE"] = "+15555550103"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from action_router.config import Config  # noqa: E402


@pytest.fixture
def dry_config(tmp_path: Path) -> Config:
    """Per-test Config: fully dry, isolated media dir."""
    return Config(
        anthropic_api_key="",
        elevenlabs_api_key="",
        twilio_account_sid="",
        twilio_auth_token="",
        twilio_from_number="+15555550100",
        homeowner_phone="+15555550101",
        emergency_dispatch_phone="+15555550102",
        family_phone="+15555550103",
        public_base_url="https://example.test",
        media_dir=tmp_path / "media",
        dry_run=True,
        use_claude=False,
        use_elevenlabs=False,
        return_flow_enabled=False,
        return_log_path=tmp_path / "return_log.jsonl",
        amazon_storage_state=tmp_path / "amazon_storage_state.json",
    )
