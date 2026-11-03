"""Kayak car-rental results (headless browser; `pricefinder[browser]`).

Kayak aggregates agency-direct rates (Hertz, Avis, Budget, Enterprise, Sixt, ...) and OTAs
(Priceline, Expedia, EconomyBookings, ...) in one results page that renders client-side.
The results URL is deterministic: `/cars/<IATA>-a<cityId>/<YYYY-MM-DD>-<HH>h/<YYYY-MM-DD>-<HH>h`.
Kayak accepts pick-up/drop-off times at hour granularity only.
"""

from __future__ import annotations

import logging
import re
from datetime import time
from decimal import Decimal
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser, LexborNode

from ...config import Settings, get_settings
from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ...fetch.browser import browser_page, page_text, playwright_available, wait_for_prices
from ...savings.base import load_yaml
from ..base import Provider, ProviderContext

log = logging.getLogger(__name__)

_BASE = "https://www.kayak.com"
_SMARTY = "/mvm/smartyv2/search?f=j&s=13&lc=en&v=v2&cv=5&dir=cars&where="
_AGENCIES = (
    "hertz",
    "avis",
    "budget",
    "enterprise",
    "national",
    "alamo",
    "sixt",
    "dollar",
    "thrifty",
    "fox",
    "payless",
    "europcar",
    "ace",
    "nu car",
    "turo",
    "routes",
    "advantage",
    "easirent",
    "zezgo",
)
_MAX_CARDS = 300
# Kayak's `fs=carclass=` filter only understands these values (Economy/Compact/... are ignored by the page).
_CLASS_FILTERS = {"suv": "SUV", "luxury": "Luxury", "van": "Van", "convertible": "Convertible"}
_SCORE = re.compile(r"offer from (?P<provider>.+?) has a score of (?P<score>[\d.]+)", re.I)
_MONEY = re.compile(r"\$\s?(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)")


def _text(node: LexborNode | None) -> str:
    return node.text(strip=True) if node is not None else ""


def _money(text: str) -> Decimal | None:
    m = _MONEY.search(text or "")
    return Decimal(m.group(1).replace(",", "")) if m else None


def _attr(card: LexborNode, label: str) -> str:
    n = card.css_first(f'[aria-label="{label}"]')
    return _text(n)


def parse_results(html: str) -> list[dict]:
    """Parse a Kayak cars results page into result dicts (pure; unit-tested on a saved capture)."""
    tree = LexborHTMLParser(html)
    out: list[dict] = []
    for card in tree.css("div.js-result"):
        title = _text(card.css_first(".js-title"))
        if not title:
            continue
        sub = _text(card.css_first(".MseY-sub-title"))
        vehicle_class = re.sub(r"^or similar\s*", "", sub).strip() or None
        agency = None
        vehicle_alt = ""
        for img in card.css("img"):
            alt = (img.attributes.get("alt") or "").strip()
            if alt.lower().startswith("vehicle type"):
                vehicle_alt = alt
            elif alt and len(alt) < 40:
                agency = re.sub(r"^car agency:\s*", "", alt, flags=re.I).strip() or None
        supplier_choice = title.lower() == "supplier choice"
        if supplier_choice:
            # Kayak hides the agency and exact model until booking; the size is assigned at pick-up.
            m = re.search(r"Vehicle type:\s*(.+?)\s*-", vehicle_alt)
            vehicle_class = m.group(1).strip() if m and "supplier" not in m.group(1).lower() else None
            title = "Supplier choice"
        score = None
        score_label = card.css_first(".NEXN-score-and-message")
        if score_label is not None and (m := _SCORE.search(score_label.attributes.get("aria-label") or "")):
            score = float(m.group("score"))
        sites: list[tuple[str, Decimal]] = []
        main_name = _text(card.css_first(".EuxN-provider-name"))
        main_price = _money(_text(card.css_first(".c4nz8-price-total")))
        if main_name and main_price is not None:
            sites.append((main_name, main_price))
        for alt_site in card.css(".OcBh"):
            name = _text(alt_site.css_first(".OcBh-provider-name"))
            price = _money(_text(alt_site.css_first(".OcBh-price")))
            if name and price is not None and not name.lower().endswith("more sites"):
                sites.append((name, price))
        if not sites:
            continue
        badge = _text(card.css_first(".z6uD"))
        out.append(
            {
                "car": title,
                "vehicle_class": vehicle_class,
                "agency": agency,
                "passengers": _attr(card, "Passengers count") or None,
                "bags": _attr(card, "Bags count") or None,
                "doors": _attr(card, "Door count") or None,
                "pickup_location": _text(card.css_first(".NYO--first-row")) or None,
                "pickup_note": _text(card.css_first(".NYO--second-row")) or None,
                "score": score,
                "free_cancellation": "free cancellation" in card.text().lower(),
                "badge": badge or None,
                "supplier_choice": supplier_choice,
                "sites": sites,
            }
        )
    return out


def results_url(slug: str, query: Query) -> str:
    assert query.dates and query.dates.end
    pu = (query.pickup_time or time(12, 0)).hour
    do = (query.dropoff_time or query.pickup_time or time(12, 0)).hour
    url = f"{_BASE}/cars/{slug}/{query.dates.start.isoformat()}-{pu}h/{query.dates.end.isoformat()}-{do}h?sort=price_a"
    if query.vehicle_class and (cls := _CLASS_FILTERS.get(query.vehicle_class.lower())):
        url += f"&fs=carclass={cls}"
    return url


class KayakCarsProvider(Provider):
    name = "kayak_cars"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.CAR_RENTAL})
    description = "Kayak car rentals: every major agency + OTAs in one page (headless browser)"
    typical_latency_s = 30.0

    def __init__(self) -> None:
        self._slugs: dict[str, str] | None = None

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

    def _known_slug(self, code: str, settings: Settings) -> str | None:
        if self._slugs is None:
            data = load_yaml(settings.rental_locations_path)
            self._slugs = (
                {k.upper(): str(v) for k, v in (data.get("kayak") or {}).items()} if isinstance(data, dict) else {}
            )
        return self._slugs.get(code.upper())

    async def _resolve_slug(self, page, where: str) -> str | None:
        """Ask Kayak's location lookup for the airport/city and build the results slug."""
        raw = await page.evaluate(
            "(u) => fetch(u, {credentials: 'include'}).then(r => r.json()).catch(() => null)", _SMARTY + quote(where)
        )
        if not raw:
            return None
        for item in raw:
            ctid = item.get("ctid")
            if not ctid:
                continue
            if item.get("loctype") == "ap" and item.get("ap"):
                return f"{item['ap']}-a{ctid}"
            city = re.sub(r"[^A-Za-z0-9]+", "-", item.get("cityonly") or item.get("name") or "").strip("-")
            if city:
                return f"{city}-c{ctid}"
        return None

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.dates and query.dates.end):
            log.info("kayak_cars: need pickup and drop-off dates")
            return []
        loc = query.destination or query.location or query.origin
        where = (loc.iata or loc.text or "") if loc else ""
        if not where:
            return []
        slug = self._known_slug(where, ctx.settings)
        async with browser_page() as page:
            if slug is None:
                await page.goto(f"{_BASE}/cars", wait_until="domcontentloaded", timeout=45000)
                slug = await self._resolve_slug(page, where)
                if slug is None:
                    log.info("kayak_cars: could not resolve location %r", where)
                    return []
            url = results_url(slug, query)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            min_prices = 5 if "fs=carclass" in url else 20  # class-filtered lists can be short
            await wait_for_prices(page, min_prices=min_prices, timeout_s=max(ctx.timeout - 15, 20), settle_s=5.0)
            # Results keep streaming in for a bit; give the page a moment after the first batch.
            stable = 0
            last = -1
            for _ in range(8):
                n = len(_MONEY.findall(await page_text(page)))
                stable = stable + 1 if n == last else 0
                last = n
                if stable >= 2:
                    break
                await page.wait_for_timeout(3000)
            # Kayak renders cards lazily; keep scrolling until the (price-sorted) list stops growing.
            cards, stale = 0, 0
            for _ in range(40):
                await page.mouse.wheel(0, 6000)
                await page.wait_for_timeout(1200)
                for sel in ('button:has-text("Show more results")', 'button:has-text("Show more")'):
                    more = page.locator(sel).first
                    if await more.count() and await more.is_visible():
                        await more.click(timeout=2000)
                        await page.wait_for_timeout(1500)
                        break
                n = await page.evaluate("document.querySelectorAll('div.js-result').length")
                stale = stale + 1 if n <= cards else 0
                cards = max(cards, n)
                if stale >= 3 or cards >= _MAX_CARDS:
                    break
            html = await page.content()
        days = max(query.dates.nights or 1, 1)
        offers: list[Offer] = []
        for r in parse_results(html):
            for site_name, total in r["sites"]:
                lname = site_name.lower()
                direct = any(a in lname for a in _AGENCIES)
                agency = r["agency"] or (site_name if direct else None)
                if r["supplier_choice"]:
                    title = "Supplier choice (model and size assigned at pick-up)"
                else:
                    title = f"{r['car']} or similar ({r['vehicle_class'] or 'car'})"
                if agency and agency.lower() not in lname:
                    title += f" from {agency}"
                title += f" via {site_name}, {days} days"
                offers.append(
                    Offer(
                        id=self.make_offer_id(
                            slug, query.cache_key(), re.sub(r"\W+", "-", r["car"].lower()), re.sub(r"\W+", "-", lname)
                        ),
                        provider=self.name,
                        vertical=Vertical.CAR_RENTAL,
                        title=title,
                        url=url,
                        seller=Seller(
                            name=site_name,
                            type=SellerType.DIRECT if direct else SellerType.OTA,
                            merchant_id=re.sub(r"[^a-z0-9]", "", lname),
                        ),
                        base_price=Money(amount=total, currency=query.currency),
                        in_stock=True,
                        location=loc,
                        attributes={
                            "car": r["car"],
                            "vehicle_class": r["vehicle_class"],
                            "agency": agency,
                            "passengers": r["passengers"],
                            "bags": r["bags"],
                            "doors": r["doors"],
                            "pickup_location": r["pickup_location"],
                            "pickup_note": r["pickup_note"],
                            "kayak_score": r["score"],
                            "free_cancellation": r["free_cancellation"],
                            "supplier_choice": r["supplier_choice"],
                            "badge": r["badge"],
                            "per_day": float((total / days).quantize(Decimal("0.01"))),
                            "days": days,
                            "times_rounded_to_hour": True,
                            "total_includes_taxes_fees": True,
                        },
                    )
                )
        return offers
