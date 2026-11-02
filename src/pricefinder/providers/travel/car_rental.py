"""Car rental aggregation. Planned: Kayak/Priceline/Expedia rate scraping with browser automation,
plus direct agency APIs (Hertz, Avis, Enterprise), Turo, Costco Travel and AutoSlash-style
coupon-code sweeps (AAA, Costco, USAA, corporate discount codes).
"""

from __future__ import annotations

from ...core.models import ProviderKind, Vertical
from ..base import NotYetImplementedProvider


class CarRentalProvider(NotYetImplementedProvider):
    name = "car_rental"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.CAR_RENTAL})
    description = "Car rental rates across agencies, OTAs, Turo, and membership codes (planned)"
    planned_approach = "browser automation + agency APIs + discount-code sweep"
