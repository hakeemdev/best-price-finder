from __future__ import annotations

import re
from decimal import Decimal

_MONEY = re.compile(r"\$\s?(\d{1,6}(?:,\d{3})*)")


def money(text: str | None) -> Decimal | None:
    m = _MONEY.search(text or "")
    return Decimal(m.group(1).replace(",", "")) if m else None


async def wait_for_cards(page, selector: str, *, minimum: int, timeout_s: float, settle_s: float = 3.0) -> int:
    """Poll until at least `minimum` result cards exist (or time runs out); returns the count."""
    waited, n = 0.0, 0
    while waited < timeout_s:
        n = await page.evaluate(f"document.querySelectorAll('{selector}').length")
        if n >= minimum:
            await page.wait_for_timeout(int(settle_s * 1000))
            return await page.evaluate(f"document.querySelectorAll('{selector}').length")
        await page.wait_for_timeout(1500)
        waited += 1.5
    return n


async def scroll(page, times: int = 6, pixels: int = 3500, pause_ms: int = 900) -> None:
    for _ in range(times):
        await page.mouse.wheel(0, pixels)
        await page.wait_for_timeout(pause_ms)
