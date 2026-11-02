# Writing a provider

A provider turns a `Query` into a list of `Offer`s. That's it.

```python
from pricefinder.core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from pricefinder.providers.base import Provider, ProviderContext


class AcmeProvider(Provider):
    name = "acme"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.GOODS})
    description = "Acme store catalog"
    required_settings = ("acme_api_key",)  # attribute names on pricefinder.config.Settings

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        resp = await ctx.client().get("https://api.acme.example/search", params={"q": query.item})
        resp.raise_for_status()
        return [
            Offer(
                id=self.make_offer_id(item["sku"]),
                provider=self.name,
                vertical=Vertical.GOODS,
                title=item["name"],
                url=item["url"],
                seller=Seller(name="Acme", type=SellerType.RETAILER, merchant_id="acme"),
                base_price=Money(amount=item["price"], currency="USD"),
                shipping=Money(amount=item.get("shipping", 0)),
                in_stock=item.get("in_stock"),
                identifiers={"upc": item.get("upc")} if item.get("upc") else {},
                raw=item,
            )
            for item in resp.json()["items"]
        ]
```

Register it in `pyproject.toml`:

```toml
[project.entry-points."pricefinder.providers"]
acme = "mypackage.acme:AcmeProvider"
```

Rules of thumb:

- Use `ctx.client()` for HTTP. It retries, rate-limits per host and caches GETs for a minute.
- Return sticker prices only. Do not apply coupons or rewards; the savings layer does that.
- Fill `seller.merchant_id` with a stable lowercase key (e.g. `bestbuy`) so coupon / cashback / card-bonus catalogs can match it.
- Fill `identifiers` (upc/ean/asin) whenever possible so history can track the product across sellers.
- Set `distance_km` and `location` for local / in-store results.
- Add a new setting to `config.Settings` for any credential and list it in `required_settings`; the provider is auto-skipped when it's missing.
- Mark `opt_in = True` for sources whose terms forbid automated access; the engine will not call them unless explicitly requested.
- Keep `typical_latency_s` honest so timeouts can be budgeted.
