"""Refresh the local cache of recent Amazon orders.

Uses the saved storage_state.json (from setup_amazon_session.py) to load the
order history page, then asks Claude to extract the recent order list as
structured JSON. Writes to ./media/amazon_orders.json (override with
AMAZON_ORDERS_CACHE).

Run periodically (cron, on demand, after a delivery notification). The
identifier reads this cache to match a stolen package against an order.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from action_router.config import CONFIG

ORDERS_URL = "https://www.amazon.com/gp/your-account/order-history"
EXTRACT_MODEL = "claude-sonnet-4-5"

EXTRACT_PROMPT = """You are given the visible HTML of an Amazon order history page.
Extract the recent orders as JSON. For each order include:
- order_id (the "Order #" string, e.g. "112-1234567-1234567")
- order_date (ISO 8601 if possible, else the raw string)
- delivered_date (ISO if shown, else null)
- items: list of {asin, title, image_url}

ASIN is a 10-character alphanumeric typically embedded in product URLs as /dp/ASIN/
or /gp/product/ASIN/. Extract it from links if visible.

Return ONLY a JSON array. No prose, no code fences. If you can't see any orders,
return [].
"""


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed.")
        return 2
    try:
        import anthropic
    except ImportError:
        print("anthropic not installed.")
        return 2

    storage = Path(os.environ.get("AMAZON_STORAGE_STATE", str(CONFIG.amazon_storage_state)))
    if not storage.exists():
        print(f"No storage_state at {storage}. Run scripts/setup_amazon_session.py first.")
        return 1

    cache_path = Path(os.environ.get("AMAZON_ORDERS_CACHE", str(CONFIG.amazon_orders_cache)))
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(storage), viewport={"width": 1280, "height": 1600}
        )
        page = context.new_page()
        page.goto(ORDERS_URL, timeout=45_000)
        if "/ap/signin" in page.url:
            print("Session expired. Re-run scripts/setup_amazon_session.py.")
            browser.close()
            return 1

        # Pull only the orders region — full page HTML is huge and noisy.
        try:
            html = page.locator("#ordersContainer").first.inner_html(timeout=15_000)
        except Exception:
            html = page.content()
        browser.close()

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": EXTRACT_PROMPT},
            {"type": "text", "text": f"<html>\n{html[:120_000]}\n</html>"},
        ]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        orders = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"Claude returned non-JSON: {exc}\nRaw:\n{text[:500]}")
        return 1
    if not isinstance(orders, list):
        print("Expected JSON array.")
        return 1

    cache_path.write_text(json.dumps(orders, indent=2))
    print(f"Wrote {len(orders)} orders to {cache_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
