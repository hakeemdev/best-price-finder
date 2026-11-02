"""Headless browser helper for sources that only render prices client-side.

Requires `pricefinder[browser]` and `playwright install chromium`. Browser providers call
`BrowserSession.page()` and are responsible for their own waiting / parsing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_PRICE_RE = re.compile(r"\$\s?\d{1,5}(?:,\d{3})*(?:\.\d{2})?")
_BLOCK_MARKERS = ("press & hold", "are you a person or a robot", "bot or not", "access to this page has been denied")


def playwright_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


@asynccontextmanager
async def browser_page(*, timezone: str = "America/New_York", headless: bool = True) -> AsyncIterator[Any]:
    """Yield a fresh Playwright page in an isolated context; closes everything on exit."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            ctx = await browser.new_context(
                user_agent=DEFAULT_UA,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                timezone_id=timezone,
            )
            page = await ctx.new_page()
            yield page
        finally:
            await browser.close()


async def page_text(page: Any) -> str:
    return await page.evaluate("document.body ? document.body.innerText : ''")


def looks_blocked(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _BLOCK_MARKERS)


async def wait_for_prices(page: Any, *, min_prices: int = 5, timeout_s: float = 40.0, settle_s: float = 4.0) -> str:
    """Poll the page until at least `min_prices` dollar amounts are visible, then wait one more
    `settle_s` for late results. Returns the final body text. Raises RuntimeError on a bot wall."""
    waited = 0.0
    text = ""
    while waited < timeout_s:
        await page.wait_for_timeout(int(settle_s * 1000))
        waited += settle_s
        text = await page_text(page)
        if looks_blocked(text):
            raise RuntimeError("bot protection page served")
        if len(_PRICE_RE.findall(text)) >= min_prices:
            await page.wait_for_timeout(int(settle_s * 1000))
            return await page_text(page)
    return text
