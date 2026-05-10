"""Phone-as-third-eye: pair any phone via QR scan and stream its camera
into the existing vision pipeline.

The phone opens an HTTPS page (served through the existing ngrok tunnel),
captures camera frames with `getUserMedia`, and pushes JPEG bytes over a
WebSocket. The action router holds the latest frame per token in memory and
republishes it as an MJPEG stream so the vision engine can consume it
through `cv2.VideoCapture(<mjpg url>)` exactly the same way it consumes the
laptop webcam — no other plumbing changes needed.
"""

from .routes import create_phone_camera_router
from .store import FrameStore, get_frame_store

__all__ = ["create_phone_camera_router", "FrameStore", "get_frame_store"]
