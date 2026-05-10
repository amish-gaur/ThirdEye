"""Browser-agent driver for Amazon returns.

Drop-in replacement for `amazon_return.initiate_return`. Same `ReturnResult`
contract — `return_flow.py` doesn't care which executor it calls.

Why an agent instead of hand-written selectors:
- Amazon's return DOM varies by item type and changes constantly. Selectors
  rot; an agent reads the page and decides clicks per step.
- Multi-item orders, "non-returnable", "choose refund method", gift-receipt
  prompts — natural-language branching the old `get_by_role("checkbox").first`
  code couldn't handle.

Auth note: still requires `amazon_storage_state.json`. The agent is
explicitly told NOT to attempt sign-in — Amazon will challenge agent-driven
logins and burn the session.

Dry-run is enforced by intercepting clicks, not by exiting early. The agent
runs the full plan and we block only the final commit. You see exactly what
*would* have happened in the screenshot trail.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .amazon_return import DEFAULT_RETURN_REASON, ReturnResult
from .config import CONFIG, Config

log = logging.getLogger("action_router.amazon_return_agent")

MODEL = "claude-sonnet-4-5"
MAX_STEPS = 25  # cost circuit-breaker; a return shouldn't need >~10 actions
VIEWPORT = {"width": 1280, "height": 800}
SUBMIT_HINTS = ("submit", "place your return", "confirm return", "complete return")

SYSTEM_TEMPLATE = """You are filing a return on Amazon for a homeowner whose package was stolen off their porch.
You are driving a Chromium browser already loaded with the homeowner's session and already on the return page for the order.

Goal: file a return for the specified order, reason="{reason}".

Hard rules:
- If you see /ap/signin or any login challenge, STOP and report "auth_expired". Do NOT try to log in.
- If the item is non-returnable, requires contacting the seller, or asks to call support, STOP and report.
- For multi-item orders, select ONLY the item matching the given ASIN. If no ASIN is provided and the order has multiple items, STOP and report "ambiguous_multi_item".
- After the return is filed, capture the confirmation text (look for an RMA id like "RMA1234..." or a return reference) before stopping.
- Be deliberate. One click at a time. Wait for the page to settle before the next action."""


def initiate_return(
    order_id: str,
    *,
    incident_id: str,
    asin: Optional[str] = None,
    reason: str = DEFAULT_RETURN_REASON,
    evidence_url: Optional[str] = None,
    config: Optional[Config] = None,
) -> ReturnResult:
    cfg = config or CONFIG
    result = ReturnResult(
        ok=False, order_id=order_id, dry_run=cfg.amazon_dry_run, reason=reason
    )
    _ = evidence_url  # logged upstream; agent doesn't need it

    if not order_id:
        result.error = "no order_id"
        return result

    storage_state_path = str(cfg.amazon_storage_state)
    if not os.path.exists(storage_state_path):
        log.warning("storage_state missing at %s; run homeowner setup first", storage_state_path)
        result.error = "missing_storage_state"
        return result

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        result.error = "playwright_not_installed"
        return result

    try:
        import anthropic  # type: ignore
    except ImportError:
        result.error = "anthropic_not_installed"
        return result

    shots_dir = os.path.join(str(cfg.media_dir), "returns", incident_id)
    os.makedirs(shots_dir, exist_ok=True)

    client = anthropic.Anthropic()

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=150)
            context = browser.new_context(
                storage_state=storage_state_path, viewport=VIEWPORT
            )
            page = context.new_page()

            page.goto(
                f"https://www.amazon.com/gp/orc/returns/homepage.html?orderId={order_id}",
                timeout=30_000,
            )
            result.steps.append("nav_return_flow")

            if "/ap/signin" in page.url:
                _shot(page, shots_dir, "auth_expired", result)
                result.error = "auth_expired"
                browser.close()
                return result

            initial_b64 = _shot(page, shots_dir, "00_start", result, return_b64=True)
            user_goal = (
                f"Order id: {order_id}. "
                f"ASIN: {asin or 'NOT PROVIDED — stop if order has multiple items'}. "
                f"Reason: {reason}. "
                f"The browser is already on the Amazon return page for this order."
            )
            messages: List[Dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_goal},
                        _image_block(initial_b64),
                    ],
                }
            ]

            for step in range(MAX_STEPS):
                resp = client.beta.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=SYSTEM_TEMPLATE.format(reason=reason),
                    tools=[
                        {
                            "type": "computer_20250124",
                            "name": "computer",
                            "display_width_px": VIEWPORT["width"],
                            "display_height_px": VIEWPORT["height"],
                        }
                    ],
                    messages=messages,
                    betas=["computer-use-2025-01-24"],
                )
                messages.append({"role": "assistant", "content": resp.content})

                tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                if resp.stop_reason == "end_turn" or not tool_uses:
                    text = "".join(
                        getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
                    )
                    result.steps.append(f"agent_done: {text[:200]}")
                    rma = _extract_rma(text)
                    if rma:
                        result.return_id = rma
                        result.ok = True
                    elif cfg.amazon_dry_run:
                        # Dry-run: agent stopped at the submit gate as expected.
                        result.ok = True
                    else:
                        result.error = "agent_stopped_without_confirmation"
                    break

                tool_results: List[Dict[str, Any]] = []
                for block in tool_uses:
                    action = block.input or {}
                    out = _execute(page, action, cfg, result, shots_dir)
                    label = action.get("action", "?")
                    coord = action.get("coordinate", "")
                    result.steps.append(f"{label}@{coord}" if coord else label)

                    if "screenshot" in out:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": [_image_block(out["screenshot"])],
                            }
                        )
                    else:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": [{"type": "text", "text": str(out)}],
                                "is_error": "error" in out,
                            }
                        )

                messages.append({"role": "user", "content": tool_results})
            else:
                result.error = "agent_step_cap_exceeded"

            browser.close()
            return result

    except Exception as exc:
        log.exception("agent return failed for order %s", order_id)
        result.error = f"unhandled: {exc}"
        return result


def _execute(
    page, action: Dict[str, Any], cfg: Config, result: ReturnResult, shots_dir: str
) -> Dict[str, Any]:
    """Translate one computer-use action into Playwright. Dry-run blocks submits."""
    t = action.get("action")
    try:
        if t in ("left_click", "double_click"):
            x, y = action["coordinate"]
            if cfg.amazon_dry_run and _looks_like_submit(page, x, y):
                result.steps.append("dry_run_blocked_submit")
                _shot(page, shots_dir, "dry_run_blocked", result)
                return {"blocked": "dry_run", "screenshot": _shot(page, shots_dir, "post_block", result, return_b64=True)}
            page.mouse.click(x, y, click_count=2 if t == "double_click" else 1)
        elif t == "right_click":
            x, y = action["coordinate"]
            page.mouse.click(x, y, button="right")
        elif t == "mouse_move":
            x, y = action["coordinate"]
            page.mouse.move(x, y)
        elif t == "type":
            page.keyboard.type(action["text"], delay=20)
        elif t == "key":
            page.keyboard.press(action["text"])
        elif t == "scroll":
            amount = int(action.get("scroll_amount", 3)) * 100
            direction = action.get("scroll_direction", "down")
            dy = amount if direction == "down" else -amount
            page.mouse.wheel(0, dy)
        elif t == "screenshot":
            pass
        elif t == "wait":
            time.sleep(min(float(action.get("duration", 1)), 5.0))
        else:
            return {"error": f"unsupported_action: {t}"}

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass

        return {"screenshot": _shot(page, shots_dir, t or "step", result, return_b64=True)}
    except Exception as exc:
        return {"error": f"{t}_failed: {exc}"}


def _looks_like_submit(page, x: int, y: int) -> bool:
    """Cheap dry-run guardrail: peek at the element under the cursor."""
    try:
        text = page.evaluate(
            "([x,y]) => { const e = document.elementFromPoint(x, y); return e ? (e.innerText || e.value || '') : ''; }",
            [x, y],
        ) or ""
        lowered = text.lower()
        return any(hint in lowered for hint in SUBMIT_HINTS)
    except Exception:
        return False


def _shot(page, shots_dir: str, label: str, result: ReturnResult, return_b64: bool = False):
    """Save a screenshot to disk and optionally return its base64."""
    try:
        png = page.screenshot(full_page=False)
    except Exception:
        log.exception("screenshot %s failed", label)
        return "" if return_b64 else None
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in label)
    path = os.path.join(shots_dir, f"{int(time.time() * 1000)}_{safe}.png")
    try:
        with open(path, "wb") as f:
            f.write(png)
        result.screenshots.append(path)
    except OSError:
        log.exception("write screenshot %s failed", path)
    if return_b64:
        return base64.b64encode(png).decode()
    return None


def _image_block(b64: str) -> Dict[str, Any]:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": b64},
    }


def _extract_rma(text: str) -> Optional[str]:
    cleaned = text.replace(",", " ").replace(".", " ").replace(":", " ")
    for tok in cleaned.split():
        if (tok.startswith("RMA") and len(tok) > 4) or (tok.startswith("ret-") and len(tok) > 6):
            return tok
    return None
