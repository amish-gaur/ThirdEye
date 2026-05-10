"""Append-only JSONL log of every return decision.

One line per incident. Used to:
- Tune confidence thresholds with real data
- Reverse a bad auto-return when the homeowner texts STOP within the
  undo window
- Reconstruct what happened when Amazon flags the account
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from .config import CONFIG, Config

log = logging.getLogger("action_router.return_log")

_lock = threading.Lock()


def append(entry: Dict[str, Any], config: Optional[Config] = None) -> None:
    cfg = config or CONFIG
    path = str(cfg.return_log_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = dict(entry)
    payload.setdefault("logged_at", time.time())
    line = json.dumps(payload, ensure_ascii=True)
    with _lock:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    log.info(
        "return_log path=%s incident=%s order=%s decision=%s",
        path,
        payload.get("incident_id"),
        payload.get("order_id"),
        payload.get("decision"),
    )
