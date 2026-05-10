"""Tiny QR code generator wrapper.

Uses the `qrcode` Python package (which only needs Pillow, already a
project dep). Wrapped so callers don't have to know about Pillow's quirky
buffering API.
"""

from __future__ import annotations

import io


def render_qr_png(text: str, *, box_size: int = 8, border: int = 2) -> bytes:
    """Render `text` as a black-on-white PNG QR code and return raw PNG bytes."""
    import qrcode  # imported lazily so a missing optional dep doesn't break import time
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
