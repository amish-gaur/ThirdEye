"""One-time interactive Amazon login. Saves Playwright storage_state.json
so the agent can drive returns on this account without seeing /ap/signin.

Run on the homeowner's machine:
    python -m scripts.setup_amazon_session

A Chromium window opens on amazon.com/sign-in. Log in (handle 2FA, captcha,
"approve from your phone", whatever Amazon throws at you). When you see
your Account page, come back to the terminal and press ENTER.
The session is written to ./media/amazon_storage_state.json (override with
AMAZON_STORAGE_STATE env var).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from action_router.config import CONFIG

LOGIN_URL = (
    "https://www.amazon.com/ap/signin?"
    "openid.return_to=https%3A%2F%2Fwww.amazon.com%2F%3Fref_%3Dnav_ya_signin&"
    "openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&"
    "openid.assoc_handle=usflex&"
    "openid.mode=checkid_setup&"
    "openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&"
    "openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0"
)
SUCCESS_HINT_URL = "https://www.amazon.com/gp/css/homepage.html"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        return 2

    out_path = Path(os.environ.get("AMAZON_STORAGE_STATE", str(CONFIG.amazon_storage_state)))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Saving session to: {out_path}")
    print("Opening Chromium. Log in to Amazon, then return here.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(LOGIN_URL, timeout=60_000)

        try:
            input("Press ENTER once you're fully logged in (Account page visible)...")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            browser.close()
            return 130

        # Best-effort sanity check — skip if the page/browser was already closed.
        try:
            page.goto(SUCCESS_HINT_URL, timeout=15_000)
            if "/ap/signin" in page.url:
                print("Still on sign-in. Session NOT saved. Try again.")
                browser.close()
                return 1
        except Exception as exc:
            print(f"(skipping post-login check: {exc.__class__.__name__}) — saving session anyway.")

        try:
            context.storage_state(path=str(out_path))
        finally:
            try:
                browser.close()
            except Exception:
                pass

    print(f"Saved storage_state to {out_path}")
    print("You can close this window. Return flow is now wired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
