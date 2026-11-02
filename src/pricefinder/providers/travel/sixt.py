"""Sixt direct rates via the public booking funnel (headless browser; `pricefinder[browser]`).

Sixt renders its offer list client-side from a deep link that carries branch id, dates and times, so
no form driving is needed. Branch ids per airport live in `data/rental_locations.yaml`.
"""

from __future__ import annotations

import logging
import re
from datetime import time
from decimal import Decimal
from urllib.parse import urlencode

from ...config import Settings, get_settings
from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ...fetch.browser import browser_page, playwright_available, wait_for_prices
from ...savings.base import load_yaml
from ..base import Provider, ProviderContext

log = logging.getLogger(__name__)

_FUNNEL = "https://www.sixt.com/betafunnel/#/offerlist"
_VEHICLE = re.compile(
    r"(?P<cls>[A-Z0-9][A-Z0-9 ]+?) \((?P<model>[^)]+)\)\n\nor similar \| (?P<body>\w+)\n"
    r"(?P<mid>.*?)\$(?P<total>\d{1,5}(?:,\d{3})*\.\d{2})total",
    re.S,
)
_PER_DAY = re.compile(r"\$(\d{1,5}(?:,\d{3})*\.\d{2})/day")
_SEATS_BAGS = re.compile(r"\n(\d+)\n(\d+)\n(Automatic|Manual)")


def parse_offerlist(text: str) -> list[dict]:
    """Parse the visible text of a Sixt offer list into vehicle dicts (pure; unit-tested)."""
    out: list[dict] = []
    for m in _VEHICLE.finditer(text):
        mid = m.group("mid")
        per_day = _PER_DAY.search(mid)
        sb = _SEATS_BAGS.search(mid)
        out.append(
            {
                "vehicle_class": m.group("cls").strip().title(),
                "model": m.group("model").title(),
                "body": m.group("body").lower(),
                "total": Decimal(m.group("total").replace(",", "")),
                "per_day": Decimal(per_day.group(1).replace(",", "")) if per_day else None,
                "seats": int(sb.group(1)) if sb else None,
                "bags": int(sb.group(2)) if sb else None,
                "transmission": sb.group(3).lower() if sb else None,
                "unlimited_miles": "Unlimited miles" in mid,
                "hot_offer": "Hot offer" in mid,
            }
        )
    return out


def funnel_url(branch_id: int, query: Query) -> str:
    assert query.dates and query.dates.end
    pu = query.pickup_time or time(12, 0)
    do = query.dropoff_time or pu
    params = {
        "uci": branch_id,
        "rci": branch_id,
        "uda": query.dates.start.strftime("%Y%m%d"),
        "rda": query.dates.end.strftime("%Y%m%d"),
        "uti": pu.strftime("%H%M"),
        "rti": do.strftime("%H%M"),
        "zen_pu_time": f"{query.dates.start.isoformat()}T{pu.strftime('%H:%M')}",
        "zen_do_time": f"{query.dates.end.isoformat()}T{do.strftime('%H:%M')}",
        "zen_vehicle_type": "car",
    }
    return f"{_FUNNEL}?{urlencode(params)}"


class SixtDirectProvider(Provider):
    name = "sixt"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.CAR_RENTAL})
    description = "Sixt agency-direct rates (headless browser)"
    typical_latency_s = 15.0

    def __init__(self) -> None:
        self._locations: dict[str, int] | None = None

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

    def branch_for(self, query: Query, settings: Settings) -> int | None:
        if self._locations is None:
            data = load_yaml(settings.rental_locations_path)
            self._locations = (
                {k.upper(): int(v) for k, v in (data.get("sixt") or {}).items()} if isinstance(data, dict) else {}
            )
        loc = query.destination or query.location or query.origin
        code = (loc.iata if loc and loc.iata else (loc.text if loc else "") or "").strip().upper()
        return self._locations.get(code)

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.dates and query.dates.end):
            log.info("sixt: need pickup and drop-off dates")
            return []
        branch = self.branch_for(query, ctx.settings)
        if branch is None:
            log.info(
                "sixt: no branch id for %s; add it to %s",
                query.destination or query.location,
                ctx.settings.rental_locations_path,
            )
            return []
        url = funnel_url(branch, query)
        async with browser_page() as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            text = await wait_for_prices(page, min_prices=4, timeout_s=ctx.timeout - 10)
        days = max(query.dates.nights or 1, 1)
        offers: list[Offer] = []
        for v in parse_offerlist(text):
            offers.append(
                Offer(
                    id=self.make_offer_id(
                        str(branch),
                        query.cache_key(),
                        v["vehicle_class"].lower().replace(" ", "-"),
                        v["model"].lower().replace(" ", "-"),
                    ),
                    provider=self.name,
                    vertical=Vertical.CAR_RENTAL,
                    title=f"Sixt {v['vehicle_class']}: {v['model']} or similar ({v['body']}), {days} days",
                    url=url,
                    seller=Seller(name="Sixt", type=SellerType.DIRECT, merchant_id="sixt"),
                    base_price=Money(amount=v["total"], currency=query.currency),
                    in_stock=True,
                    location=query.destination or query.location,
                    attributes={
                        "vehicle_class": v["vehicle_class"],
                        "model": v["model"],
                        "body": v["body"],
                        "per_day": float(v["per_day"]) if v["per_day"] else None,
                        "seats": v["seats"],
                        "bags": v["bags"],
                        "transmission": v["transmission"],
                        "unlimited_miles": v["unlimited_miles"],
                        "days": days,
                        "pickup": f"{query.dates.start} {query.pickup_time or ''}".strip(),
                        "dropoff": f"{query.dates.end} {query.dropoff_time or ''}".strip(),
                        "total_includes_taxes_fees": True,
                    },
                )
            )
        return offers
