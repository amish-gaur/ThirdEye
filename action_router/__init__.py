"""SafeWatch action router (Person 2).

Public surface:
    execute_action(event_json) -> ActionResult
    Config, CONFIG
"""

from .config import CONFIG, Config
from .router import ActionResult, execute_action

__all__ = ["CONFIG", "Config", "ActionResult", "execute_action"]
