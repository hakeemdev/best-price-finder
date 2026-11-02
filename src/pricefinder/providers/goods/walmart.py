"""Walmart Affiliate API (walmart.io). Requires PF_WALMART_CONSUMER_ID and PF_WALMART_PRIVATE_KEY_PATH
(an RSA private key PEM registered with your walmart.io application) and `pricefinder[walmart]`.

Auth: each request is signed with RSA-SHA256 over "consumerId\\ntimestamp\\nkeyVersion\\n".
Docs: https://walmart.io/docs/affiliate/v1/introduction
"""

from __future__ import annotations

import base64
import time
from decimal import Decimal
from pathlib import Path

from ...core.models import Condition, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ..base import Provider, ProviderContext

_SEARCH_URL = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2/search"


def sign_request(
    consumer_id: str, key_version: str, private_key_pem: bytes, timestamp_ms: int | None = None
) -> dict[str, str]:
    """Build the four Walmart auth headers. Exposed for tests and for other Walmart endpoints."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    ts = str(timestamp_ms or int(time.time() * 1000))
    canonical = f"{consumer_id}\n{ts}\n{key_version}\n".encode()
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    return {
        "WM_CONSUMER.ID": consumer_id,
        "WM_CONSUMER.INTIMESTAMP": ts,
        "WM_SEC.KEY_VERSION": key_version,
        "WM_SEC.AUTH_SIGNATURE": base64.b64encode(signature).decode(),
    }


class WalmartProvider(Provider):
    name = "walmart"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.GOODS})
    description = "Walmart.com + marketplace sellers (official affiliate API)"
    required_settings = ("walmart_consumer_id", "walmart_private_key_path")
    typical_latency_s = 2.0

    def __init__(self) -> None:
        self._pem: bytes | None = None

    def _private_key(self, ctx: ProviderContext) -> bytes:
        if self._pem is None:
            self._pem = Path(ctx.settings.walmart_private_key_path or "").read_bytes()
        return self._pem

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        s = ctx.settings
        headers = sign_request(s.walmart_consumer_id or "", s.walmart_key_version, self._private_key(ctx))
        headers["Accept"] = "application/json"
        params: dict = {"query": query.item, "numItems": 25, "sort": "price", "order": "ascending"}
        if query.max_price:
            params["maxPrice"] = str(query.max_price.amount)
        resp = await ctx.client().get(_SEARCH_URL, params=params, headers=headers)
        resp.raise_for_status()
        return [
            self._to_offer(item, query) for item in resp.json().get("items", []) if item.get("salePrice") is not None
        ]

    def _to_offer(self, item: dict, query: Query) -> Offer:
        price = Decimal(str(item["salePrice"]))
        ship_rate = item.get("standardShipRate")
        free_ship = bool(item.get("freeShippingOver35Dollars") and price >= 35) or ship_rate in (0, 0.0, None)
        marketplace = bool(item.get("marketplace"))
        seller_name = (item.get("sellerInfo") or "Walmart") if marketplace else "Walmart"
        return Offer(
            id=self.make_offer_id(str(item.get("itemId", ""))),
            provider=self.name,
            vertical=Vertical.GOODS,
            title=item.get("name", ""),
            url=item.get("productUrl") or item.get("productTrackingUrl"),
            seller=Seller(
                name=seller_name,
                type=SellerType.RESELLER if marketplace else SellerType.RETAILER,
                rating=float(item["customerRating"]) if item.get("customerRating") else None,
                review_count=item.get("numReviews"),
                merchant_id="walmart",
            ),
            base_price=Money(amount=price, currency=query.currency),
            shipping=Money.zero(query.currency)
            if free_ship
            else Money(amount=Decimal(str(ship_rate)), currency=query.currency),
            condition=Condition.NEW,
            in_stock=(item.get("stock") or "").lower() == "available" or bool(item.get("availableOnline")),
            image_url=item.get("thumbnailImage") or item.get("mediumImage"),
            identifiers={
                k: str(v)
                for k, v in {
                    "upc": item.get("upc"),
                    "walmart_item_id": item.get("itemId"),
                    "mpn": item.get("modelNumber"),
                }.items()
                if v
            },
            attributes={"msrp": item.get("msrp"), "marketplace": marketplace, "category": item.get("categoryPath")},
            raw=item,
        )
