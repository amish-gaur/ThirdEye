"""Step 3b: ElevenLabs turns the script into an MP3 file on disk.

The MP3 is written into `MEDIA_DIR` and exposed by the FastAPI service at
`/media/<filename>`. Twilio fetches it from `PUBLIC_BASE_URL/media/<filename>`.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from .config import CONFIG, Config

log = logging.getLogger("action_router.tts")


def synthesize_mp3(
    script: str,
    config: Config | None = None,
    filename: Optional[str] = None,
) -> Path:
    """Write `script` to an MP3 inside `MEDIA_DIR` and return the path.

    Raises RuntimeError on failure so the caller can fall back to TwiML <Say>.
    """
    cfg = config or CONFIG
    media_dir = cfg.ensure_media_dir()
    name = filename or f"alert_{uuid.uuid4().hex[:12]}.mp3"
    out_path = media_dir / name

    if not cfg.use_elevenlabs or not cfg.elevenlabs_api_key:
        raise RuntimeError("ElevenLabs disabled or missing API key")

    try:
        from elevenlabs.client import ElevenLabs  # local import for startup speed
    except ImportError as exc:
        raise RuntimeError(f"elevenlabs SDK not installed: {exc}") from exc

    client = ElevenLabs(api_key=cfg.elevenlabs_api_key)
    try:
        audio_iter = client.text_to_speech.convert(
            text=script,
            voice_id=cfg.elevenlabs_voice_id,
            model_id=cfg.elevenlabs_model_id,
            output_format=cfg.elevenlabs_output_format,
        )
    except Exception as exc:
        raise RuntimeError(f"ElevenLabs convert() failed: {exc}") from exc

    bytes_written = 0
    with out_path.open("wb") as f:
        for chunk in audio_iter:
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode()
            f.write(chunk)
            bytes_written += len(chunk)

    if bytes_written == 0:
        out_path.unlink(missing_ok=True)
        raise RuntimeError("ElevenLabs returned 0 bytes")

    log.info("Synthesized %d bytes -> %s", bytes_written, out_path)
    return out_path
