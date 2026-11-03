"""Airbnb search results (headless browser; `pricefinder[browser]`).

Airbnb has no price sort, so the adapter reads the default page, then re-queries with a nightly price cap
pitched just above the cheapest nightly rate it saw, which surfaces the bottom of the market. Card totals
are the stay price before taxes (service fee included); Airbnb only adds taxes at checkout.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser

from ...config import Settings, get_settings
from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ...fetch.browser import browser_page, looks_blocked, page_text, playwright_available
from ..base import Provider, ProviderContext
from ._common import scroll, wait_for_cards

log = logging.getLogger(__name__)

_BASE = "https://www.airbnb.com"
_TOTAL = re.compile(r"\$\s?([\d,]+)\s+for\s+(\d+)\s+nights?", re.I)
_ORIGINAL = re.compile(r"originally\s+\$\s?([\d,]+)", re.I)
_CREDIT = re.compile(r"\+\s?\$\s?([\d,]+)\s+Airbnb credit", re.I)
_RATING = re.compile(r"([\d.]+)\s+out of 5 average rating,\s*([\d,]+)\s+reviews?", re.I)
_BEDROOMS = re.compile(r"\b(\d+)\s+bedrooms?\b", re.I)
_BEDS = re.compile(r"\b(\d+)\s+(?:[a-z]+\s+)?beds?\b", re.I)
_ROOM_ID = re.compile(r"/rooms/(\d+)")
_KIND_TITLE = re.compile(r"^[A-Za-z][A-Za-z -]{1,30}\s+in\s+\S", re.I)


def place_slug(place: str) -> str:
    parts = [re.sub(r"[^A-Za-z0-9]+", "-", p.strip()).strip("-") for p in place.split(",")]
    return "--".join(p for p in parts if p)


def search_url(place: str, query: Query, *, price_max: int | None = None) -> str:
    assert query.dates and query.dates.end
    url = (
        f"{_BASE}/s/{place_slug(place)}/homes?checkin={query.dates.start.isoformat()}"
        f"&checkout={query.dates.end.isoformat()}&adults={max(query.travelers.adults, 1)}"
    )
    if query.travelers.children:
        url += f"&children={query.travelers.children}"
    if price_max:
        url += f"&price_min=0&price_max={int(price_max)}"
    return url


def parse_results(html: str) -> list[dict]:
    tree = LexborHTMLParser(html)
    rows: list[dict] = []
    for card in tree.css('[data-testid="card-container"]'):
        text = card.text(separator="|", strip=True)
        m = _TOTAL.search(text)
        if not m:
            continue
        title_node = card.css_first('[data-testid="listing-card-title"]')
        kind_node = card.css_first('[data-testid="listing-card-subtitle"]')
        title = title_node.text(strip=True) if title_node else ""
        subtitle = kind_node.text(strip=True) if kind_node else ""
        # Homes are titled "Apartment in Dallas" with the host's name as subtitle; listed hotels are the reverse.
        if _KIND_TITLE.match(title) and not _KIND_TITLE.match(subtitle):
            kind, name = title, subtitle
        else:
            kind, name = subtitle, title
        link = card.css_first('a[href*="/rooms/"]')
        rid = _ROOM_ID.search(link.attributes.get("href", "")) if link else None
        rating = _RATING.search(text)
        rows.append(
            {
                "id": rid.group(1) if rid else None,
                "title": name or title,
                "kind": kind,
                "total": Decimal(m.group(1).replace(",", "")),
                "nights": int(m.group(2)),
                "original_total": Decimal(o.group(1).replace(",", "")) if (o := _ORIGINAL.search(text)) else None,
                "airbnb_credit": Decimal(c.group(1).replace(",", "")) if (c := _CREDIT.search(text)) else None,
                "rating": float(rating.group(1)) if rating else None,
                "reviews": int(rating.group(2).replace(",", "")) if rating else None,
                "bedrooms": int(b.group(1)) if (b := _BEDROOMS.search(text)) else None,
                "beds": int(b.group(1)) if (b := _BEDS.search(text)) else None,
                "featured_hotel": "featured hotel" in text.lower(),
                "guest_favorite": "guest favorite" in text.lower(),
                "free_cancellation": "free cancellation" in text.lower(),
            }
        )
    return rows


class AirbnbProvider(Provider):
    name = "airbnb"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.HOTEL})
    description = "Airbnb homes, rooms and listed hotels (headless browser)"
    typical_latency_s = 40.0

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

    async def _load(self, page, url: str, timeout_s: float) -> str:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cards(page, '[data-testid="card-container"]', minimum=8, timeout_s=timeout_s)
        if looks_blocked(await page_text(page)):
            raise RuntimeError("bot protection page served")
        await scroll(page, times=5)
        return await page.content()

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.dates and query.dates.end):
            log.info("airbnb: need check-in and check-out dates")
            return []
        loc = query.destination or query.location
        place = (loc.text if loc else "") or ""
        if not place:
            return []
        rows: dict[str, dict] = {}
        async with browser_page(timezone="America/Chicago", headless=ctx.settings.browser_headless) as page:
            first = parse_results(await self._load(page, search_url(place, query), min(ctx.timeout / 3, 40)))
            for r in first:
                rows[r["id"] or r["title"]] = r
            if first:
                cheapest_nightly = min(r["total"] / max(r["nights"], 1) for r in first)
                cap = int(max(40, min(250, cheapest_nightly * 2)))
                if query.max_price:
                    cap = int(query.max_price.amount / max(query.dates.nights or 1, 1))
                cheap = parse_results(await self._load(page, search_url(place, query, price_max=cap), 30))
                for r in cheap:
                    rows.setdefault(r["id"] or r["title"], r)
        nights = max(query.dates.nights or 1, 1)
        offers: list[Offer] = []
        for key, r in rows.items():
            if r["nights"] != nights:
                # Airbnb pads thin results with listings available for a slightly different stay; not comparable.
                continue
            url = (
                f"{_BASE}/rooms/{r['id']}?adults={max(query.travelers.adults, 1)}"
                f"&check_in={query.dates.start.isoformat()}&check_out={query.dates.end.isoformat()}"
                if r["id"]
                else search_url(place, query)
            )
            kind = r["kind"] or ("Hotel" if r["featured_hotel"] else "Home")
            offers.append(
                Offer(
                    id=self.make_offer_id(self.name, query.cache_key(), key),
                    provider=self.name,
                    vertical=Vertical.HOTEL,
                    title=f"{r['title']} ({kind}), {r['nights']} nights via Airbnb",
                    url=url,
                    seller=Seller(name="Airbnb", type=SellerType.OTA, merchant_id="airbnb"),
                    base_price=Money(amount=r["total"], currency=query.currency),
                    in_stock=True,
                    location=loc,
                    attributes={
                        "kind": kind,
                        "nights": r["nights"],
                        "nightly": (r["total"] / max(r["nights"], 1)).quantize(Decimal("0.01")),
                        "rating": r["rating"],
                        "reviews": r["reviews"],
                        "bedrooms": r["bedrooms"],
                        "beds": r["beds"],
                        "original_total": r["original_total"],
                        "airbnb_credit": r["airbnb_credit"],
                        "featured_hotel": r["featured_hotel"],
                        "guest_favorite": r["guest_favorite"],
                        "free_cancellation": r["free_cancellation"],
                        "total_includes_taxes_fees": False,
                        "price_note": "stay total before taxes; Airbnb adds occupancy tax at checkout",
                    },
                )
            )
        return offers
