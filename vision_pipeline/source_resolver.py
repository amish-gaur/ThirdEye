"""Resolve `CAMERA_SOURCE` strings into something `cv2.VideoCapture` accepts.

Supports the regular OpenCV inputs (integer device index, RTSP URL, file path)
PLUS a `phone://` shortcut so a paired phone can be used as a video source
just like the laptop webcam:

    phone                              → http://127.0.0.1:8001/camera/default/stream.mjpg
    phone:lobby                        → http://127.0.0.1:8001/camera/lobby/stream.mjpg
    phone://lobby                      → http://127.0.0.1:8001/camera/lobby/stream.mjpg
    phone://192.168.1.20:8001/lobby    → http://192.168.1.20:8001/camera/lobby/stream.mjpg

The resolver is intentionally pure-string so it can be unit-tested without
spinning up the action router.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

DEFAULT_TOKEN = "default"
DEFAULT_BASE = "http://127.0.0.1:8001"


def _strip_scheme(s: str, scheme: str) -> str:
    if s.startswith(scheme):
        return s[len(scheme):]
    return s


def _normalize_base(base: str) -> str:
    base = base.strip().rstrip("/")
    if not base:
        return DEFAULT_BASE
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base


def resolve_camera_source(
    raw: str,
    *,
    default_base: str | None = None,
) -> int | str:
    """Resolve a CAMERA_SOURCE string.

    Returns either a device index (int) or a URL/path string suitable for
    `cv2.VideoCapture`. The `phone` shortcuts are turned into MJPEG URLs that
    point at the action router's phone-camera stream endpoint.
    """
    raw = (raw or "").strip()
    base = _normalize_base(
        default_base
        or os.getenv("PHONE_CAMERA_BASE_URL")
        or os.getenv("ACTION_ROUTER_BASE_URL")
        or DEFAULT_BASE
    )

    if not raw:
        return 0
    if raw.isdigit():
        return int(raw)

    lower = raw.lower()
    if lower == "phone":
        return f"{base}/camera/{DEFAULT_TOKEN}/stream.mjpg"
    if lower.startswith("phone://"):
        rest = _strip_scheme(raw, "phone://")
        return _phone_url(rest, default_base=base)
    if lower.startswith("phone:"):
        rest = _strip_scheme(raw, "phone:")
        return _phone_url(rest, default_base=base)

    return raw


def _phone_url(rest: str, *, default_base: str) -> str:
    """Build the MJPEG URL from the `phone:`/`phone://` body.

    Body forms:
      "lobby"                 → token only, use default base
      "host:port/lobby"       → custom host + token
      "https://host/lobby"    → fully-qualified base + token
    """
    rest = rest.strip().lstrip("/")
    if not rest:
        return f"{default_base}/camera/{DEFAULT_TOKEN}/stream.mjpg"

    # Accept fully-qualified base URLs (with their own scheme).
    if rest.startswith(("http://", "https://")):
        parsed = urlparse(rest)
        token = (parsed.path or "").strip("/") or DEFAULT_TOKEN
        base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return f"{base}/camera/{token}/stream.mjpg"

    # If there's a slash, treat the first segment as host (or host:port) and
    # the remainder as a token. Otherwise it's just a token.
    if "/" in rest:
        host_part, token = rest.split("/", 1)
        token = token.strip("/") or DEFAULT_TOKEN
        base = _normalize_base(host_part)
        return f"{base}/camera/{token}/stream.mjpg"

    # No slash: ambiguous between host (with port) and token. If it contains a
    # colon it's clearly a host:port, not a token; use it with default token.
    if ":" in rest and not rest.endswith(":"):
        base = _normalize_base(rest)
        return f"{base}/camera/{DEFAULT_TOKEN}/stream.mjpg"

    # Plain token.
    return f"{default_base}/camera/{rest}/stream.mjpg"
