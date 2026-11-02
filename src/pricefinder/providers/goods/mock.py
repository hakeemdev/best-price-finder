"""Deterministic offers for tests, demos and CI. Always available; never touches the network."""

from __future__ import annotations

from decimal import Decimal

from ...core.models import Condition, Location, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ..base import Provider, ProviderContext


class MockGoodsProvider(Provider):
    name = "mock"
    kind = ProviderKind.MOCK
    verticals = frozenset({Vertical.GOODS, Vertical.FLIGHT, Vertical.HOTEL, Vertical.CAR_RENTAL, Vertical.RESERVATION})
    description = "Deterministic sample data (no network)"

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        base = Decimal(len(query.item) * 7 % 400 + 99)
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
