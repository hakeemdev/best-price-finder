"""Booking.com search results sorted by price (headless browser; `pricefinder[browser]`).

Cards carry the stay total for the requested nights and guests. US properties usually quote before taxes;
when a card says "Includes taxes and fees" or "+$X taxes and fees" the adapter records that.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from urllib.parse import quote_plus

from selectolax.lexbor import LexborHTMLParser

from ...config import Settings, get_settings
from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ...fetch.browser import browser_page, looks_blocked, page_text, playwright_available
from ..base import Provider, ProviderContext
from ._common import money, scroll, wait_for_cards

log = logging.getLogger(__name__)

_BASE = "https://www.booking.com"
_TOTAL = re.compile(r"Price\s+\$\s?([\d,]+)", re.I)
_NIGHTLY = re.compile(r"Per night\s*\|?\s*\$\s?([\d,]+)", re.I)
_ORIGINAL = re.compile(r"Original price\s+\$\s?([\d,]+)", re.I)
_TAXES = re.compile(r"\+\s?\$\s?([\d,]+)\s+taxes and (?:charges|fees)", re.I)
_SCORE = re.compile(r"Scored\s+([\d.]+)", re.I)
_REVIEWS = re.compile(r"([\d,]+)\s+reviews?", re.I)
_STAY = re.compile(r"(\d+)\s+nights?,\s*(\d+)\s+adults?", re.I)


def search_url(place: str, query: Query) -> str:
    assert query.dates and query.dates.end
    return (
        f"{_BASE}/searchresults.html?ss={quote_plus(place)}&checkin={query.dates.start.isoformat()}"
        f"&checkout={query.dates.end.isoformat()}&group_adults={max(query.travelers.adults, 1)}"
        f"&no_rooms={max(query.travelers.rooms, 1)}&group_children={query.travelers.children}"
        f"&order=price&selected_currency={query.currency}"
    )


def _text(node) -> str:
    return node.text(strip=True) if node is not None else ""


def parse_results(html: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    rows: list[dict] = []
    for card in tree.css('[data-testid="property-card"]'):
        text = card.text(separator="|", strip=True)
        total = _TOTAL.search(text)
        if not total:
            continue
        link = card.css_first('a[data-testid="title-link"]')
        href = (link.attributes.get("href") or "").split("?")[0] if link else ""
        units = card.css_first('[data-testid="recommended-units"]')
        room = units.text(separator="|", strip=True).split("|")[0] if units else ""
        stay = _STAY.search(text)
        rows.append(
            {
                "name": _text(card.css_first('[data-testid="title"]')),
                "url": href,
                "room": room,
                "unit": _text(card.css_first('[data-testid="property-card-unit-configuration"]')),
                "distance": _text(card.css_first('[data-testid="distance"]')),
                "total": Decimal(total.group(1).replace(",", "")),
                "nightly": money(_NIGHTLY.search(text).group(0)) if _NIGHTLY.search(text) else None,
                "original_total": money(_ORIGINAL.search(text).group(0)) if _ORIGINAL.search(text) else None,
                "taxes": money(_TAXES.search(text).group(0)) if _TAXES.search(text) else None,
                "taxes_included": bool(re.search(r"includes taxes and (?:charges|fees)", text, re.I)),
                "score": float(s.group(1)) if (s := _SCORE.search(text)) else None,
                "reviews": int(r.group(1).replace(",", "")) if (r := _REVIEWS.search(text)) else None,
                "nights": int(stay.group(1)) if stay else None,
                "adults": int(stay.group(2)) if stay else None,
                "free_cancellation": "free cancellation" in text.lower(),
                "pay_at_property": "no prepayment needed" in text.lower(),
                "breakfast": "breakfast included" in text.lower(),
            }
        )
    return rows


class BookingProvider(Provider):
    name = "booking_com"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.HOTEL})
    description = "Booking.com hotels, hostels and rentals sorted by price (headless browser)"
    typical_latency_s = 35.0

    def is_available(self, settings: Settings | None = None) -> bool:
        settings = settings or get_settings()
        return settings.browser_providers_enabled and playwright_available()

    def missing_settings(self, settings: Settings | None = None) -> list[str]:
        settings = settings or get_settings()
        out = []
        if not settings.browser_providers_enabled:
            out.append("browser_providers_enabled")
        if not playwright_available():
            out.append("playwright (pip install 'pricefinder[browser]' && playwright install chromium)")
        return out

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.dates and query.dates.end):
            log.info("booking_com: need check-in and check-out dates")
            return []
        loc = query.destination or query.location
        place = (loc.text if loc else "") or ""
        if not place:
            return []
        url = search_url(place, query)
        async with browser_page(timezone="America/Chicago", headless=ctx.settings.browser_headless) as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await wait_for_cards(page, '[data-testid="property-card"]', minimum=10, timeout_s=min(ctx.timeout / 2, 45))
            if looks_blocked(await page_text(page)):
                raise RuntimeError("bot protection page served")
            for _ in range(3):
                await scroll(page, times=4)
                more = page.locator('button:has-text("Load more results")').first
                if await more.count() and await more.is_visible():
                    await more.click(timeout=3000)
                    await page.wait_for_timeout(2500)
            html = await page.content()
        rows = parse_results(html)
        nights = max(query.dates.nights or 1, 1)
        offers: list[Offer] = []
        for r in rows:
            link = (
                f"{r['url']}?checkin={query.dates.start.isoformat()}&checkout={query.dates.end.isoformat()}"
                f"&group_adults={max(query.travelers.adults, 1)}&no_rooms={max(query.travelers.rooms, 1)}"
                if r["url"]
                else url
            )
            offers.append(
                Offer(
                    id=self.make_offer_id(
                        self.name, query.cache_key(), re.sub(r"\W+", "-", r["name"].lower()), r["room"][:20]
                    ),
                    provider=self.name,
                    vertical=Vertical.HOTEL,
                    title=f"{r['name']}: {r['room'] or r['unit']}, {r['nights'] or nights} nights via Booking.com",
                    url=link,
                    seller=Seller(name="Booking.com", type=SellerType.OTA, merchant_id="booking"),
                    base_price=Money(amount=r["total"], currency=query.currency),
                    taxes=Money(amount=r["taxes"], currency=query.currency) if r["taxes"] else None,
                    in_stock=True,
                    location=loc,
                    attributes={
                        "kind": r["unit"] or "room",
                        "room": r["room"],
                        "nights": r["nights"] or nights,
                        "nightly": r["nightly"] or (r["total"] / nights).quantize(Decimal("0.01")),
                        "score": r["score"],
                        "reviews": r["reviews"],
                        "distance": r["distance"],
                        "original_total": r["original_total"],
                        "free_cancellation": r["free_cancellation"],
                        "pay_at_property": r["pay_at_property"],
                        "breakfast": r["breakfast"],
                        "total_includes_taxes_fees": r["taxes_included"],
                        "price_note": "includes taxes and fees"
                        if r["taxes_included"]
                        else ("taxes and fees added" if r["taxes"] else "stay total before taxes and fees"),
                    },
                )
            )
        return offers
