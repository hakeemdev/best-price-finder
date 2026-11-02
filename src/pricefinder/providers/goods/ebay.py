"""eBay Browse API (official). Requires PF_EBAY_CLIENT_ID / PF_EBAY_CLIENT_SECRET.

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

from __future__ import annotations

import base64
import time
from decimal import Decimal

from ...core.models import Condition, Location, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ..base import Provider, ProviderContext

_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_CONDITION_MAP = {
    "NEW": Condition.NEW,
    "OPEN_BOX": Condition.OPEN_BOX,
    "CERTIFIED_REFURBISHED": Condition.REFURBISHED,
    "SELLER_REFURBISHED": Condition.REFURBISHED,
    "USED": Condition.USED,
}


class EbayProvider(Provider):
    name = "ebay"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.GOODS})
    description = "eBay listings via the official Browse API"
    required_settings = ("ebay_client_id", "ebay_client_secret")

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expiry = 0.0

    async def _get_token(self, ctx: ProviderContext) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        s = ctx.settings
        creds = base64.b64encode(f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()).decode()
        resp = await ctx.client().post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + int(body.get("expires_in", 7200))
        return self._token

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        token = await self._get_token(ctx)
        filters = ["buyingOptions:{FIXED_PRICE}"]
        if query.max_price:
            filters.append(f"price:[..{query.max_price.amount}],priceCurrency:{query.currency}")
        if query.conditions:
            ids = {
                Condition.NEW: "1000",
                Condition.OPEN_BOX: "1500",
                Condition.REFURBISHED: "2000|2500",
                Condition.USED: "3000",
            }
            filters.append("conditionIds:{" + "|".join(ids[c] for c in query.conditions if c in ids) + "}")
        params = {"q": query.item, "limit": "50", "filter": ",".join(filters), "sort": "price"}
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }
        if ctx.settings.home_postal_code:
            headers["X-EBAY-C-ENDUSERCTX"] = (
                f"contextualLocation=country={ctx.settings.home_country},zip={ctx.settings.home_postal_code}"
            )
        resp = await ctx.client().get(_SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        return [self._to_offer(item, query) for item in resp.json().get("itemSummaries", [])]

    def _to_offer(self, item: dict, query: Query) -> Offer:
        price = item.get("price", {})
        ship = (item.get("shippingOptions") or [{}])[0].get("shippingCost")
        seller = item.get("seller", {})
        loc = item.get("itemLocation", {})
        return Offer(
            id=self.make_offer_id(item.get("itemId", "")),
            provider=self.name,
            vertical=Vertical.GOODS,
            title=item.get("title", ""),
            url=item.get("itemWebUrl"),
            seller=Seller(
                name=seller.get("username", "eBay seller"),
                type=SellerType.MARKETPLACE_INDIVIDUAL,
                rating=(float(seller["feedbackPercentage"]) / 20) if seller.get("feedbackPercentage") else None,
                review_count=seller.get("feedbackScore"),
                merchant_id="ebay",
            ),
            base_price=Money(amount=Decimal(price.get("value", "0")), currency=price.get("currency", query.currency)),
            shipping=Money(amount=Decimal(ship["value"]), currency=ship["currency"]) if ship else None,
            condition=_CONDITION_MAP.get(item.get("conditionId", ""), Condition.UNKNOWN),
            in_stock=True,
            location=Location(
                city=loc.get("city"),
                region=loc.get("stateOrProvince"),
                country=loc.get("country"),
                postal_code=loc.get("postalCode"),
            ),
            image_url=(item.get("image") or {}).get("imageUrl"),
            identifiers={k: v for k, v in {"epid": item.get("epid")}.items() if v},
            raw=item,
        )
