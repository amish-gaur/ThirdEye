"""Single-place verbose tracer for the post-Qwen execution pipeline.

Every call into Twilio / ElevenLabs / Messages.app / Claude flows through here
so a debug run produces a copy-pasteable log that shows exactly where the
pipeline broke.

Format:

    HH:MM:SS.mmm  thr=NNN  ▶ LABEL  field=value field=value ...

Output goes straight to stdout (flushed) so it survives whatever logging
configuration the host process uses. Keep the format machine-greppable —
any human reading a paste should be able to scan column-by-column.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any


_ENABLED = os.environ.get("THIRDEYE_TRACE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


# ANSI colors. Keep the palette small so a log paste is still readable when
# the receiver strips colors. We bias toward markers humans scan for: BEGIN
# (cyan), OK (green), ERR (red), INFO/WARN (yellow), default (none).
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_MAGENTA = "\033[95m"

_LEVEL_COLORS = {
    "BEGIN": _CYAN,
    "STEP": _MAGENTA,
    "INFO": "",
    "OK": _GREEN,
    "WARN": _YELLOW,
    "ERR": _RED,
}


def _format_value(v: Any, max_len: int = 200) -> str:
    s = repr(v) if isinstance(v, str) else str(v)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def trace(_step: str, *, level: str = "INFO", **fields: Any) -> None:
    """Print a single trace line. Always flushes stdout.

    First arg is the step name (positional only — leading underscore prevents
    a `step="..."` kwarg from colliding with payload fields like `label=`).
    `level` is one of BEGIN / STEP / INFO / OK / WARN / ERR — tints the
    label so a fast scroll catches the green/red transitions.
    """
    if not _ENABLED:
        return
    now = time.time()
    millis = int((now - int(now)) * 1000)
    ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{millis:03d}"
    thread_name = threading.current_thread().name[:14]
    color = _LEVEL_COLORS.get(level, "")
    label_text = f"{color}{_BOLD}▶ {_step:<14}{_RESET}" if color else f"▶ {_step:<14}"
    parts = [f"{_DIM}{ts}{_RESET}", f"{_DIM}{thread_name:<14}{_RESET}", label_text]
    for k, v in fields.items():
        parts.append(f"{_DIM}{k}={_RESET}{_format_value(v)}")
    sys.stdout.write("  " + "  ".join(parts) + "\n")
    sys.stdout.flush()


def trace_exception(_step: str, exc: BaseException, **fields: Any) -> None:
    """Convenience: log an exception with type and message at ERR level."""
    fields.setdefault("type", type(exc).__name__)
    fields.setdefault("msg", str(exc))
    trace(_step, level="ERR", **fields)
