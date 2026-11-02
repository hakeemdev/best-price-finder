"""Google Hotels via SerpApi. Requires PF_SERPAPI_KEY and a query with destination + dates."""

from __future__ import annotations

from ...core.models import Location, Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from .._serpapi import parse_money, serpapi_get
from ..base import Provider, ProviderContext


class GoogleHotelsProvider(Provider):
    name = "google_hotels"
    kind = ProviderKind.API
    verticals = frozenset({Vertical.HOTEL})
    description = "Google Hotels (direct + OTA rates, vacation rentals) via SerpApi"
    required_settings = ("serpapi_key",)

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        dest = query.destination or query.location
        if not (dest and query.dates and query.dates.end):
            return []
        data = await serpapi_get(
            ctx,
            engine="google_hotels",
            q=f"{query.item} {dest.text}".strip()
            if query.item and query.item.lower() not in (dest.text or "").lower()
            else dest.text,
            check_in_date=query.dates.start.isoformat(),
            check_out_date=query.dates.end.isoformat(),
            adults=query.travelers.adults,
            children=query.travelers.children or None,
            currency=query.currency,
            hl="en",
        )
        nights = query.dates.nights or 1
        offers: list[Offer] = []
        for prop in data.get("properties", []):
            total = parse_money(
                (prop.get("total_rate") or {}).get("extracted_lowest") or (prop.get("total_rate") or {}).get("lowest")
            )
            nightly = parse_money((prop.get("rate_per_night") or {}).get("extracted_lowest"))
            if total is None and nightly is not None:
                total = nightly * nights
            if total is None:
                continue
            gps = prop.get("gps_coordinates") or {}
            name = prop.get("name", "Hotel")
            # Each property may list several booking sources (direct + OTAs); emit one offer per source.
            sources = prop.get("prices") or [{"source": name, "rate_per_night": {"extracted_lowest": nightly}}]
            for src in sources:
                src_total = parse_money((src.get("total_rate") or {}).get("extracted_lowest")) or parse_money(
                    (src.get("rate_per_night") or {}).get("extracted_lowest")
                )
                if src_total is not None and src.get("total_rate") is None:
                    src_total = src_total * nights
                seller_name = src.get("source") or name
                is_direct = src.get("official") or seller_name.lower() in name.lower()
                offers.append(
                    Offer(
                        id=self.make_offer_id(prop.get("property_token", name), seller_name),
                        provider=self.name,
                        vertical=Vertical.HOTEL,
                        title=f"{name} - {nights} night{'s' if nights != 1 else ''}",
                        url=src.get("link") or prop.get("link"),
                        seller=Seller(
                            name=seller_name,
                            type=SellerType.DIRECT if is_direct else SellerType.OTA,
                            rating=prop.get("overall_rating"),
                            review_count=prop.get("reviews"),
                            merchant_id="".join(ch for ch in seller_name.lower() if ch.isalnum()),
                        ),
                        base_price=Money(amount=src_total or total, currency=query.currency),
                        in_stock=True,
                        location=Location(text=dest.text, lat=gps.get("latitude"), lon=gps.get("longitude")),
                        image_url=((prop.get("images") or [{}])[0]).get("thumbnail"),
                        attributes={
                            "hotel_class": prop.get("hotel_class"),
                            "amenities": prop.get("amenities"),
                            "nightly": float(nightly) if nightly else None,
                            "nights": nights,
                            "type": prop.get("type"),
                        },
                        raw=prop,
                    )
                )
        return offers
