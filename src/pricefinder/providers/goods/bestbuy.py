"""Best Buy Developer API: product search plus in-store availability near the user.

Requires PF_BESTBUY_API_KEY (https://developer.bestbuy.com). Emits one online offer per product and,
when a home postal code is configured, one LOCAL_STORE offer per nearby store that has it in stock,
with `distance_km` filled so the ranker can trade price against the drive.

Docs: https://bestbuyapis.github.io/api-documentation/
"""

from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal

from ...core.models import Condition, Location, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ..base import Provider, ProviderContext

log = logging.getLogger(__name__)

_BASE = "https://api.bestbuy.com/v1"
_SHOW = ",".join(
    [
        "sku",
        "name",
        "salePrice",
        "regularPrice",
        "onlineAvailability",
        "inStoreAvailability",
        "url",
        "image",
        "upc",
        "manufacturer",
        "modelNumber",
        "customerReviewAverage",
        "customerReviewCount",
        "condition",
        "shippingCost",
        "freeShipping",
    ]
)
_STORE_SHOW = (
    "sku,name,salePrice,stores.storeId,stores.name,stores.distance,stores.city,stores.region,stores.postalCode"
)
_MAX_LOCAL_LOOKUPS = 6


class BestBuyProvider(Provider):
    name = "bestbuy"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.GOODS})
    description = "Best Buy catalog + in-store stock near you (official API)"
    required_settings = ("bestbuy_api_key",)
    typical_latency_s = 2.0

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        terms = [t for t in re.split(r"[^A-Za-z0-9.+-]+", query.item) if t]
        if not terms:
            return []
        search_expr = "&".join(f"search={t}" for t in terms)
        filters = [f"({search_expr})"]
        if query.max_price:
            filters.append(f"salePrice<={query.max_price.amount}")
        if query.conditions and Condition.NEW in query.conditions and len(query.conditions) == 1:
            filters.append("condition=new")
        url = f"{_BASE}/products({'&'.join(filters)})"
        params = {
            "apiKey": ctx.settings.bestbuy_api_key,
            "format": "json",
            "show": _SHOW,
            "pageSize": 25,
            "sort": "salePrice.asc",
        }
        resp = await ctx.client().get(url, params=params)
        resp.raise_for_status()
        products = resp.json().get("products", [])
        offers = [self._online_offer(p, query) for p in products if p.get("salePrice") is not None]

        if query.include_local and ctx.settings.home_postal_code:
            local = await asyncio.gather(
                *(
                    self._store_offers(p, query, ctx)
                    for p in products[:_MAX_LOCAL_LOOKUPS]
                    if p.get("inStoreAvailability")
                )
            )
            offers.extend(o for batch in local for o in batch)
        return offers

    # -- helpers ------------------------------------------------------------

    def _online_offer(self, p: dict, query: Query) -> Offer:
        price = Decimal(str(p["salePrice"]))
        shipping = (
            Money.zero(query.currency)
            if p.get("freeShipping") or not p.get("shippingCost")
            else Money(amount=Decimal(str(p["shippingCost"])), currency=query.currency)
        )
        cond_raw = (p.get("condition") or "new").lower()
        condition = (
            Condition.REFURBISHED
            if "refurb" in cond_raw
            else Condition.OPEN_BOX
            if "open" in cond_raw
            else Condition.NEW
        )
        return Offer(
            id=self.make_offer_id(str(p.get("sku", ""))),
            provider=self.name,
            vertical=Vertical.GOODS,
            title=p.get("name", ""),
            url=p.get("url"),
            seller=Seller(
                name="Best Buy",
                type=SellerType.RETAILER,
                rating=p.get("customerReviewAverage"),
                review_count=p.get("customerReviewCount"),
                merchant_id="bestbuy",
            ),
            base_price=Money(amount=price, currency=query.currency),
            shipping=shipping,
            condition=condition,
            in_stock=bool(p.get("onlineAvailability")),
            image_url=p.get("image"),
            identifiers={
                k: str(v)
                for k, v in {"upc": p.get("upc"), "sku": p.get("sku"), "mpn": p.get("modelNumber")}.items()
                if v
            },
            attributes={
                "regular_price": p.get("regularPrice"),
                "manufacturer": p.get("manufacturer"),
                "in_store_available": p.get("inStoreAvailability"),
            },
            raw=p,
        )

    async def _store_offers(self, p: dict, query: Query, ctx: ProviderContext) -> list[Offer]:
        radius_miles = round(max(query.max_drive_km or ctx.settings.local_radius_km, 1) / 1.609)
        url = f"{_BASE}/products(sku={p['sku']})+stores(area({ctx.settings.home_postal_code},{radius_miles}))"
        params = {"apiKey": ctx.settings.bestbuy_api_key, "format": "json", "show": _STORE_SHOW}
        try:
            resp = await ctx.client().get(url, params=params)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - local lookup is best-effort
            log.debug("bestbuy store lookup failed for sku %s: %s", p.get("sku"), exc)
            return []
        out: list[Offer] = []
        for prod in resp.json().get("products", []):
            for store in prod.get("stores", []):
                distance_mi = store.get("distance")
                out.append(
                    Offer(
                        id=self.make_offer_id(str(p.get("sku", "")), f"store{store.get('storeId', '')}"),
                        provider=self.name,
                        vertical=Vertical.GOODS,
                        title=f"{p.get('name', '')} (in store: {store.get('name', 'Best Buy')})",
                        url=p.get("url"),
                        seller=Seller(name="Best Buy", type=SellerType.LOCAL_STORE, merchant_id="bestbuy"),
                        base_price=Money(
                            amount=Decimal(str(prod.get("salePrice", p["salePrice"]))), currency=query.currency
                        ),
                        shipping=Money.zero(query.currency),
                        condition=Condition.NEW,
                        in_stock=True,
                        location=Location(
                            city=store.get("city"), region=store.get("region"), postal_code=store.get("postalCode")
                        ),
                        distance_km=round(float(distance_mi) * 1.609, 1) if distance_mi is not None else None,
                        identifiers={k: str(v) for k, v in {"upc": p.get("upc"), "sku": p.get("sku")}.items() if v},
                        attributes={"store_id": store.get("storeId"), "pickup": True},
                    )
                )
        return out
