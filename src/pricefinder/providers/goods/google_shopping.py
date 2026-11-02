"""Google Shopping results via SerpApi. Requires PF_SERPAPI_KEY.

Covers Amazon, Walmart, Best Buy, Target, Newegg, B&H and thousands of smaller merchants in one call.
Direct retailer adapters (official affiliate APIs, in-store inventory) will layer on top of this.
"""

from __future__ import annotations

from ...core.models import Condition, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from .._serpapi import parse_money, serpapi_get
from ..base import Provider, ProviderContext


class GoogleShoppingProvider(Provider):
    name = "google_shopping"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.GOODS})
    description = "Google Shopping aggregate (Amazon, Walmart, Best Buy, Target, ...) via SerpApi"
    required_settings = ("serpapi_key",)

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        q = query.item
        if Condition.USED in query.conditions or Condition.REFURBISHED in query.conditions:
            q += " used OR refurbished"
        data = await serpapi_get(
            ctx,
            engine="google_shopping",
            q=q,
            gl=ctx.settings.home_country.lower(),
            hl="en",
            num=40,
            location=query.location.text if query.location and query.location.text else None,
        )
        offers: list[Offer] = []
        for item in data.get("shopping_results", []):
            price = parse_money(item.get("extracted_price") or item.get("price"))
            if price is None:
                continue
            source = item.get("source") or "Unknown"
            cond = Condition.NEW
            if item.get("second_hand_condition"):
                cond = Condition.REFURBISHED if "refurb" in item["second_hand_condition"].lower() else Condition.USED
            delivery = (item.get("delivery") or "").lower()
            shipping = Money.zero(query.currency) if "free" in delivery else None
            offers.append(
                Offer(
                    id=self.make_offer_id(item.get("product_id") or item.get("position", "")),
                    provider=self.name,
                    vertical=Vertical.GOODS,
                    title=item.get("title", ""),
                    url=item.get("product_link") or item.get("link"),
                    seller=Seller(
                        name=source,
                        type=SellerType.RETAILER,
                        rating=item.get("store_rating"),
                        review_count=item.get("store_reviews"),
                        merchant_id="".join(ch for ch in source.lower() if ch.isalnum()),
                    ),
                    base_price=Money(amount=price, currency=query.currency),
                    shipping=shipping,
                    condition=cond,
                    in_stock=None,
                    image_url=item.get("thumbnail"),
                    identifiers={k: str(v) for k, v in {"google_product_id": item.get("product_id")}.items() if v},
                    attributes={
                        "rating": item.get("rating"),
                        "reviews": item.get("reviews"),
                        "delivery": item.get("delivery"),
                    },
                    raw=item,
                )
            )
        return offers
