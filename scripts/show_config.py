"""Step 1: print the loaded config (with secrets redacted)."""

from __future__ import annotations

from dataclasses import asdict

from action_router.config import CONFIG


def _redact(key: str, val: object) -> object:
    if val is None:
        return None
    s = str(val)
    if not s:
        return "(empty)"
    sensitive = (
        "api_key",
        "auth_token",
        "account_sid",
        "phone",
        "from_number",
    )
    if any(token in key for token in sensitive):
        if len(s) <= 8:
            return "***"
        return s[:4] + "…" + s[-3:]
    return val


def main() -> None:
    cfg = asdict(CONFIG)
    width = max(len(k) for k in cfg)
    print(f"ThirdEye action-router config ({len(cfg)} keys):\n")
    for key, val in cfg.items():
        print(f"  {key:<{width}}  =  {_redact(key, val)}")


if __name__ == "__main__":
    main()
