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

## Agency-direct car rentals

| Agency | Status | Notes |
|---|---|---|
| Sixt | live (`sixt`) | public booking funnel deep link; exact times honoured |
| National | live (`national`) | home-page widget driven end to end, then "Continue as Guest"; Est. Total includes taxes and fees |
| Alamo, Enterprise | blocked | same platform as National; both answer automated sessions with a generic error after submit. Their deep links with dates prefilled are generated anyway for a human to click |
| Avis, Budget | blocked | "Access is temporarily restricted" security check after submit |
| Hertz | blocked | serves an empty page shell to headless browsers |

Kayak (`kayak_cars`) also carries agency-direct listings when an agency chooses to publish there.

**Assisted mode.** Set `PF_BROWSER_HEADLESS=false` to run the browser adapters in a visible window. The tool
drives the form as usual; if a site shows a security check you can complete it yourself and the adapter keeps
going once prices appear. The tool never tries to defeat those checks on its own.

Add `direct` (or "no third party sites", "agency-direct only") to a query to keep only sellers that fulfil the
booking themselves.

## Places to stay

| Source | Status | Notes |
|---|---|---|
| Airbnb (`airbnb`) | live | default page plus a second pass capped near the cheapest nightly rate (Airbnb has no price sort); listings quoted for a different number of nights are dropped; totals are before occupancy tax |
| Booking.com (`booking_com`) | live | results sorted by price, "Load more" expanded; totals before taxes unless the card says otherwise |
| Kayak stays | not yet | page renders; nightly vs total figures per card still need disambiguating |
| Google Hotels (`google_hotels`) | needs `PF_SERPAPI_KEY` | |

Example: `pf search "hotel or airbnb in Dallas, TX from 11/4/26 to 11/10/26 for 1 adult"`.
