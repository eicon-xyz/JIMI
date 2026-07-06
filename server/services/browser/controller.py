"""
Browser Controller — Playwright/CDP browser automation.

Provides DOM-level browser control as tools for the Execution Agent.
Unlike visual (OmniParser) interaction, DOM operations are precise:
- click(selector) hits the exact element, no coordinate drift
- get_snapshot() returns structured interactive elements, not raw HTML
- type(selector, text) fills inputs directly, no clipboard dance

Architecture:
    ExecutionAgent.dispatch_tool("browser_click", {"selector": "..."})
        → self.browser.click("...")
        → BrowserController._page.click("...")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Snapshot size guard ──
MAX_SNAPSHOT_ELEMENTS = 80  # drop elements beyond this to avoid token explosion
MAX_TEXT_LENGTH = 120        # truncate visible text per element


class BrowserController:
    """Playwright-based browser automation controller.

    Lifecycle:
        browser = BrowserController()
        await browser.start()       # launches Chromium
        await browser.navigate("https://example.com")
        snapshot = await browser.get_snapshot()
        await browser.click("#btn")
        await browser.close()       # clean shutdown
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None
        self._started = False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self, headless: bool = False) -> None:
        """Launch Chromium via Playwright.

        Args:
            headless: Run without UI. Default False so humans can watch.
        """
        if self._started:
            logger.info("BrowserController already started, reusing")
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright not installed. Run: pip install playwright && playwright install chromium"
            ) from exc

        logger.info("Starting Playwright Chromium (headless=%s)...", headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
            ],
        )
        self._page = await self._browser.new_page()
        self._started = True
        logger.info("BrowserController started successfully")

    async def close(self) -> None:
        """Close browser and stop Playwright. Safe to call multiple times."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("Error closing browser: %s", e)
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning("Error stopping playwright: %s", e)
            self._playwright = None

        self._page = None
        self._started = False
        logger.info("BrowserController closed")

    @property
    def is_started(self) -> bool:
        return self._started and self._page is not None

    # ── Page actions ─────────────────────────────────────────────────────

    async def navigate(self, url: str) -> dict:
        """Navigate to a URL. Returns page title and final URL."""
        self._ensure_started()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        logger.info("Browser navigating to: %s", url)
        response = await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        title = await self._page.title()
        return {
            "success": True,
            "url": self._page.url,
            "title": title,
            "status": response.status if response else None,
            "action_summary": f"navigated to '{title}' ({url})",
        }

    async def click(self, selector: str) -> dict:
        """Click an element by CSS selector or text.

        Supports:
            - CSS: "#id", ".class", "button", "a[href='/login']"
            - Text: "text=登录" or ":text('Login')"
            - Role: "button[name='submit']"
        """
        self._ensure_started()
        try:
            elem = self._page.locator(selector).first
            tag = await elem.evaluate("el => el.tagName.toLowerCase()")
            text = await elem.text_content() or ""
            text = text.strip()[:80]
            await elem.click(timeout=10_000)
            label = f"<{tag}>" + (f" '{text}'" if text else "")
            logger.info("Browser clicked: %s", label)
            return {
                "success": True,
                "selector": selector,
                "tag": tag,
                "text": text,
                "action_summary": f"clicked {label}",
            }
        except Exception as e:
            return self._error("click", selector, e)

    async def type(self, selector: str, text: str) -> dict:
        """Type text into an input/textarea element.

        Clears existing content first, then types.
        """
        self._ensure_started()
        try:
            elem = self._page.locator(selector).first
            await elem.click(timeout=5_000)   # focus
            await elem.fill("")               # clear
            await elem.type(text, delay=30)   # human-like typing
            logger.info("Browser typed %d chars into '%s'", len(text), selector)
            return {
                "success": True,
                "selector": selector,
                "text": text,
                "action_summary": f"typed '{text}' into '{selector}'",
            }
        except Exception as e:
            return self._error("type", selector, e)

    async def get_snapshot(self) -> dict:
        """Return a compact DOM snapshot listing interactive elements.

        NOT raw HTML — only interactive elements (links, buttons, inputs, selects)
        with their selector, tag, visible text, and input state.
        Capped at MAX_SNAPSHOT_ELEMENTS to prevent token explosion.
        """
        self._ensure_started()
        title = await self._page.title()
        url = self._page.url

        # Extract interactive elements via JS
        elements = await self._page.evaluate("""() => {
            const interactive = 'a,button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],[role="combobox"],[role="searchbox"],[role="checkbox"],[role="radio"],[contenteditable="true"],[onclick]';
            const els = document.querySelectorAll(interactive);
            const results = [];
            for (const el of els) {
                if (results.length >= %d) break;

                const rect = el.getBoundingClientRect();
                // Skip off-screen / invisible elements
                if (rect.width === 0 || rect.height === 0) continue;
                if (rect.bottom < 0 || rect.top > window.innerHeight) continue;

                const tag = el.tagName.toLowerCase();
                let text = '';
                if (tag === 'input' || tag === 'textarea') {
                    text = el.value || el.placeholder || el.getAttribute('aria-label') || el.name || '';
                } else {
                    text = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (text.length > %d) text = text.slice(0, %d) + '…';
                }
                // Only include elements with visible text or special attributes
                if (!text && tag !== 'input' && tag !== 'textarea' && tag !== 'select' && tag !== 'button') continue;

                // Build a reasonable selector
                let sel = tag;
                if (el.id) { sel = '#' + el.id; }
                else if (el.className && typeof el.className === 'string') {
                    const cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                    if (cls) sel = tag + '.' + cls;
                }

                results.push({
                    tag: tag,
                    text: text,
                    selector: sel,
                    href: tag === 'a' ? (el.href || '') : '',
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                });
            }
            return results;
        }""" % (MAX_SNAPSHOT_ELEMENTS, MAX_TEXT_LENGTH, MAX_TEXT_LENGTH))

        # Build compact text representation
        lines = [
            f"## Browser Snapshot",
            f"Title: {title}",
            f"URL: {url}",
            f"Interactive elements ({len(elements)} shown):",
            "",
        ]
        for i, el in enumerate(elements):
            tag_label = el["tag"]
            if el.get("type"):
                tag_label += f"[type={el['type']}]"
            text_str = el["text"] or "(no text)"
            sel_str = el["selector"]
            href = f" → {el['href']}" if el.get("href") else ""
            lines.append(f"  {i}  <{tag_label}> \"{text_str}\"  [{sel_str}]{href}")

        snapshot_text = "\n".join(lines)
        logger.info("Browser snapshot: %d elements, %d chars", len(elements), len(snapshot_text))
        return {
            "success": True,
            "title": title,
            "url": url,
            "elements": elements,
            "snapshot_text": snapshot_text,
            "action_summary": f"snapshot: {len(elements)} elements on '{title}'",
        }

    async def scroll(self, direction: str, amount: int = 300) -> dict:
        """Scroll the page up or down by pixel amount."""
        self._ensure_started()
        delta = amount if direction == "down" else -amount
        await self._page.evaluate(f"window.scrollBy(0, {delta})")
        logger.info("Browser scrolled %s %dpx", direction, amount)
        return {
            "success": True,
            "direction": direction,
            "amount": amount,
            "action_summary": f"scrolled {direction} {amount}px",
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        if not self._started or not self._page:
            raise RuntimeError(
                "BrowserController not started. Call await browser.start() first."
            )

    @staticmethod
    def _error(action: str, selector: str, exc: Exception) -> dict:
        msg = str(exc)[:200]
        logger.warning("Browser %s('%s') failed: %s", action, selector, msg)
        return {
            "success": False,
            "action": action,
            "selector": selector,
            "error": msg,
            "action_summary": f"{action} failed: {msg}",
        }
