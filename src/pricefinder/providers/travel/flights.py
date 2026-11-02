"""Google Flights via SerpApi. Requires PF_SERPAPI_KEY and a query with origin/destination/dates."""

from __future__ import annotations

from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from .._serpapi import parse_money, serpapi_get
from ..base import Provider, ProviderContext

_CABIN = {"economy": 1, "premium economy": 2, "business": 3, "first": 4}


class GoogleFlightsProvider(Provider):
    name = "google_flights"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.FLIGHT})
    description = "Google Flights (all airlines + OTAs) via SerpApi"
    required_settings = ("serpapi_key",)

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.origin and query.destination and query.dates):
            return []
        origin = query.origin.iata or query.origin.text
        dest = query.destination.iata or query.destination.text
        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": dest,
            "outbound_date": query.dates.start.isoformat(),
            "currency": query.currency,
            "hl": "en",
            "adults": query.travelers.adults,
            "children": query.travelers.children or None,
            "travel_class": _CABIN.get(query.cabin or "economy", 1),
            "type": 2 if (query.one_way or not query.dates.end) else 1,
            "return_date": query.dates.end.isoformat() if query.dates.end and not query.one_way else None,
        }
        data = await serpapi_get(ctx, **params)
        offers: list[Offer] = []
        for group in ("best_flights", "other_flights"):
            for itin in data.get(group, []):
                price = parse_money(itin.get("price"))
                if price is None:
                    continue
                legs = itin.get("flights", [])
                airlines = sorted({leg.get("airline", "") for leg in legs if leg.get("airline")})
                stops = max(len(legs) - 1, 0)
                title = f"{origin} -> {dest} {' / '.join(airlines)} ({'nonstop' if stops == 0 else f'{stops} stop'})"
                offers.append(
                    Offer(
                        id=self.make_offer_id(str(abs(hash(title + str(price))))),
                        provider=self.name,
                        vertical=Vertical.FLIGHT,
                        title=title,
                        url=data.get("search_metadata", {}).get("google_flights_url"),
                        seller=Seller(
                            name=airlines[0] if airlines else "Airline",
                            type=SellerType.DIRECT,
                            merchant_id=(airlines[0].lower().replace(" ", "") if airlines else None),
                        ),
                        base_price=Money(amount=price, currency=query.currency),
                        in_stock=True,
                        attributes={
                            "airlines": airlines,
                            "stops": stops,
                            "total_duration_min": itin.get("total_duration"),
                            "departure": legs[0].get("departure_airport", {}).get("time") if legs else None,
                            "arrival": legs[-1].get("arrival_airport", {}).get("time") if legs else None,
                            "carbon_kg": (itin.get("carbon_emissions") or {}).get("this_flight"),
                        },
                        raw=itin,
                    )
                )
        return offers
