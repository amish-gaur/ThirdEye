"""Browser-driven Amazon return initiation.

`initiate_return(order_id, reason, evidence_url, config)` is the only entry
point. It opens Amazon with a persisted Playwright `storage_state.json`
(homeowner logs in once during a one-time setup script), navigates to the
order, clicks "Return or replace items", picks the reason, and submits.

Design notes:
- Lazy-imports Playwright so the action_router package keeps importing on
  machines without it (tests, CI, dev boxes that don't run returns).
- Honors `AMAZON_DRY_RUN` config — when true, every step logs what it
  *would* do but never clicks Submit. Default is true; flip to false only
  on a homeowner machine that has a real authenticated session and where
  the homeowner has approved auto-returns.
- Saves a step-by-step screenshot trail to `media/returns/{incident_id}/`
  for audit. Wrong returns happen — evidence makes them recoverable.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .config import CONFIG, Config

log = logging.getLogger("action_router.amazon_return")

DEFAULT_RETURN_REASON = "Item arrived damaged / package missing"


@dataclass
class ReturnResult:
    ok: bool
    order_id: Optional[str]
    return_id: Optional[str] = None
    dry_run: bool = False
    reason: str = ""
    error: Optional[str] = None
    steps: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)


def initiate_return(
    order_id: str,
    *,
    incident_id: str,
    reason: str = DEFAULT_RETURN_REASON,
    evidence_url: Optional[str] = None,
    config: Optional[Config] = None,
) -> ReturnResult:
    """Drive a browser through Amazon's return flow.

    Returns a `ReturnResult` describing what happened. The router logs this
    to the JSONL return log. Failures degrade gracefully — caller falls back
    to evidence-only SMS if `ok` is False.
    """
    cfg = config or CONFIG
    result = ReturnResult(ok=False, order_id=order_id, dry_run=cfg.amazon_dry_run, reason=reason)

    if not order_id:
        result.error = "no order_id"
        return result

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        log.warning("Playwright is not installed; skipping return for %s", order_id)
        result.error = "playwright_not_installed"
        return result

    storage_state_path = str(cfg.amazon_storage_state)
    if not os.path.exists(storage_state_path):
        log.warning(
            "Amazon storage_state missing at %s; run the homeowner setup flow first.",
            storage_state_path,
        )
        result.error = "missing_storage_state"
        return result

    shots_dir = os.path.join(str(cfg.media_dir), "returns", incident_id)
    os.makedirs(shots_dir, exist_ok=True)

    def shot(page: object, label: str) -> None:
        path = os.path.join(shots_dir, f"{int(time.time())}_{label}.png")
        try:
            page.screenshot(path=path, full_page=True)  # type: ignore[attr-defined]
            result.screenshots.append(path)
        except Exception:
            log.exception("screenshot %s failed", label)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=200)
            context = browser.new_context(storage_state=storage_state_path)
            page = context.new_page()

            page.goto("https://www.amazon.com/gp/your-account/order-history", timeout=30_000)
            result.steps.append("nav_orders")
            shot(page, "01_orders")

            # Detect auth wall — if Amazon redirected us to /ap/signin, the
            # storage_state expired. Bail out cleanly so the homeowner can
            # re-auth instead of attempting a return on an anonymous session.
            if "/ap/signin" in page.url:
                result.error = "auth_expired"
                shot(page, "02_auth_expired")
                browser.close()
                return result

            # Open the specific order's return flow. Amazon's return entry
            # point is keyed by order id and works directly.
            return_url = (
                f"https://www.amazon.com/gp/orc/returns/homepage.html"
                f"?orderId={order_id}"
            )
            page.goto(return_url, timeout=30_000)
            result.steps.append("nav_return_flow")
            shot(page, "03_return_flow")

            # The remainder is brittle by nature (Amazon DOM changes). We
            # implement minimum-viable selectors here and let codev / the
            # homeowner harden once we have real DOM samples.
            #
            # In dry-run we stop here — proves we got into the flow on a real
            # session without committing.
            if cfg.amazon_dry_run:
                result.steps.append("dry_run_stop")
                result.ok = True
                browser.close()
                return result

            # Pick the package's first returnable item. (Real impl: select by
            # ASIN passed in alongside order_id.)
            try:
                page.get_by_role("checkbox").first.check(timeout=10_000)  # type: ignore[attr-defined]
                result.steps.append("select_item")
            except Exception as exc:
                result.error = f"select_item_failed: {exc}"
                shot(page, "04_select_item_failed")
                browser.close()
                return result

            try:
                page.get_by_role("button", name="Continue").click(timeout=10_000)  # type: ignore[attr-defined]
                result.steps.append("continue_to_reason")
                shot(page, "05_reason_page")
            except Exception as exc:
                result.error = f"continue_click_failed: {exc}"
                browser.close()
                return result

            # Fill reason. Amazon usually surfaces a dropdown / radios.
            try:
                page.get_by_label(reason).first.check(timeout=5_000)  # type: ignore[attr-defined]
                result.steps.append("pick_reason")
            except Exception:
                # Fall back to whatever's first — better than aborting.
                try:
                    page.get_by_role("radio").first.check(timeout=5_000)  # type: ignore[attr-defined]
                    result.steps.append("pick_reason_fallback")
                except Exception as exc:
                    result.error = f"reason_select_failed: {exc}"
                    browser.close()
                    return result

            try:
                page.get_by_role("button", name="Submit").click(timeout=10_000)  # type: ignore[attr-defined]
                result.steps.append("submit")
                shot(page, "06_submitted")
            except Exception as exc:
                result.error = f"submit_failed: {exc}"
                browser.close()
                return result

            # Best-effort: scrape return id off the confirmation page.
            try:
                text = page.text_content("body", timeout=5_000) or ""  # type: ignore[attr-defined]
                for token in text.split():
                    if token.startswith("RMA") or token.startswith("ret-"):
                        result.return_id = token.strip(",.")
                        break
            except Exception:
                pass

            result.ok = True
            browser.close()
            return result

    except Exception as exc:
        log.exception("Amazon return failed for order %s", order_id)
        result.error = f"unhandled: {exc}"
        return result
