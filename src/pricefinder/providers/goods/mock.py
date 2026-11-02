"""Deterministic offers for tests, demos and CI. Always available; never touches the network.

Emits vertical-appropriate sellers so the savings layer (rental codes, membership rates, card
category bonuses) can be exercised offline.
"""

from __future__ import annotations

from decimal import Decimal

from ...core.models import (
    Condition,
    Location,
    Money,
    Offer,
    ProviderKind,
    Query,
    Seller,
    SellerType,
    Vertical,
)
from ..base import Provider, ProviderContext

_TRAVEL_SELLERS: dict[Vertical, list[tuple[str, SellerType, str]]] = {
    Vertical.CAR_RENTAL: [
        ("Hertz", SellerType.DIRECT, "1.00"),
        ("Avis", SellerType.DIRECT, "0.96"),
        ("Kayak", SellerType.OTA, "0.92"),
    ],
    Vertical.FLIGHT: [
        ("Delta", SellerType.DIRECT, "1.00"),
        ("United", SellerType.DIRECT, "0.94"),
        ("Expedia", SellerType.OTA, "0.97"),
    ],
    Vertical.HOTEL: [
        ("Hyatt", SellerType.DIRECT, "1.00"),
        ("Marriott", SellerType.DIRECT, "1.05"),
        ("Hotels.com", SellerType.OTA, "0.93"),
    ],
    Vertical.RESERVATION: [("OpenTable", SellerType.OTA, "1.00"), ("Resy", SellerType.OTA, "1.00")],
}


class MockGoodsProvider(Provider):
    name = "mock"
    kind = ProviderKind.MOCK
    verticals = frozenset({Vertical.GOODS, Vertical.FLIGHT, Vertical.HOTEL, Vertical.CAR_RENTAL, Vertical.RESERVATION})
    description = "Deterministic sample data (no network)"

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        base = Decimal(len(query.item) * 7 % 400 + 99)
        if query.vertical in _TRAVEL_SELLERS:
            return self._travel(query, base)
        return self._goods(query, base)

    def _travel(self, query: Query, base: Decimal) -> list[Offer]:
        cur = query.currency
        nights = (query.dates.nights if query.dates and query.dates.nights else 3) or 3
        multiplier = Decimal(nights) if query.vertical in (Vertical.HOTEL, Vertical.CAR_RENTAL) else Decimal(1)
        label = {
            Vertical.CAR_RENTAL: f"{(query.vehicle_class or 'midsize').title()} rental, {nights} days",
            Vertical.FLIGHT: f"{query.item} {'one-way' if query.one_way else 'round trip'}",
            Vertical.HOTEL: f"{query.item.title() or 'Hotel'}, {nights} nights",
            Vertical.RESERVATION: query.item.title(),
        }[query.vertical]
        offers: list[Offer] = []
        for name, stype, factor in _TRAVEL_SELLERS[query.vertical]:
            price = (base * multiplier * Decimal(factor)).quantize(Decimal("0.01"))
            fees = (
                Money(amount=(price * Decimal("0.12")).quantize(Decimal("0.01")), currency=cur)
                if stype == SellerType.DIRECT
                else None
            )
            offers.append(
                Offer(
                    id=self.make_offer_id(name.lower().replace(".", ""), query.cache_key()),
                    provider=self.name,
                    vertical=query.vertical,
                    title=f"{label} via {name}",
                    url=f"https://example.com/mock/{name.lower().replace(' ', '')}",
                    seller=Seller(
                        name=name,
                        type=stype,
                        rating=4.3,
                        merchant_id="".join(ch for ch in name.lower() if ch.isalnum()),
                    ),
                    base_price=Money(amount=price, currency=cur),
                    taxes=fees,
                    in_stock=True,
                    location=query.destination or query.location,
                    attributes={"nights": nights, "sample": True},
                )
            )
        return offers

    def _goods(self, query: Query, base: Decimal) -> list[Offer]:
        cur = query.currency
        title = query.item.title()
        return [
            Offer(
                id=self.make_offer_id("retail", query.cache_key()),
                provider=self.name,
                vertical=query.vertical,
                title=f"{title} (Mock Retailer)",
                url="https://example.com/mock/retail",
                seller=Seller(name="Mock", type=SellerType.RETAILER, rating=4.7, merchant_id="mock"),
                base_price=Money(amount=base, currency=cur),
                shipping=Money.zero(cur),
                taxes=Money(amount=(base * Decimal("0.0825")).quantize(Decimal("0.01")), currency=cur),
                condition=Condition.NEW,
                in_stock=True,
                identifiers={"upc": "000000000001"},
            ),
            Offer(
                id=self.make_offer_id("marketplace", query.cache_key()),
                provider=self.name,
                vertical=query.vertical,
                title=f"{title} - used, great condition",
                url="https://example.com/mock/marketplace",
                seller=Seller(name="Local Seller", type=SellerType.MARKETPLACE_INDIVIDUAL, rating=None),
                base_price=Money(amount=(base * Decimal("0.7")).quantize(Decimal("0.01")), currency=cur),
                condition=Condition.USED,
                in_stock=True,
                location=Location(text="12 km away"),
                distance_km=12,
                identifiers={"upc": "000000000001"},
            ),
            Offer(
                id=self.make_offer_id("bigbox", query.cache_key()),
                provider=self.name,
                vertical=query.vertical,
                title=f"{title} (Big Box, in store)",
                url="https://example.com/mock/bigbox",
                seller=Seller(name="BestBuy", type=SellerType.LOCAL_STORE, rating=4.4, merchant_id="bestbuy"),
                base_price=Money(amount=base + 20, currency=cur),
                taxes=Money(amount=((base + 20) * Decimal("0.0825")).quantize(Decimal("0.01")), currency=cur),
                condition=Condition.NEW,
                in_stock=True,
                distance_km=4,
                identifiers={"upc": "000000000001"},
            ),
        ]
