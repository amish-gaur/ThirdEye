"""Step 1: API vault. All env vars in one place."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    anthropic_fallback_model: str = os.getenv("ANTHROPIC_FALLBACK_MODEL", "claude-haiku-4-5")

    # ElevenLabs
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    elevenlabs_model_id: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")
    elevenlabs_output_format: str = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")

    # Twilio
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from_number: str = os.getenv("TWILIO_FROM_NUMBER", "")

    # Demo phones
    homeowner_phone: str = os.getenv("HOMEOWNER_PHONE", "")
    emergency_dispatch_phone: str = os.getenv("EMERGENCY_DISPATCH_PHONE", "")
    family_phone: str = os.getenv("FAMILY_PHONE", "")

    # Service
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _int("PORT", 8001)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    media_dir: Path = Path(os.getenv("MEDIA_DIR", "./media"))

    # Behavior knobs
    dry_run: bool = _bool("DRY_RUN", False)
    use_claude: bool = _bool("USE_CLAUDE", True)
    # Default false: Twilio <Say> works without keys; <Play> needs ElevenLabs + public URL.
    use_elevenlabs: bool = _bool("USE_ELEVENLABS", False)

    def elevenlabs_play_enabled(self) -> bool:
        """True only when MP3 <Play> can actually work (key + Twilio-reachable base URL)."""
        if not self.use_elevenlabs:
            return False
        key = (self.elevenlabs_api_key or "").strip()
        if not key or key in {"...", "ELEVENLABS_API_KEY"}:
            return False
        base = (self.public_base_url or "").lower().rstrip("/")
        if "127.0.0.1" in base or "localhost" in base:
            return False
        return True

    def media_url(self, filename: str) -> str:
        return f"{self.public_base_url}/media/{filename}"

    def ensure_media_dir(self) -> Path:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        return self.media_dir


CONFIG = Config()
