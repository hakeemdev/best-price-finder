"""Nearby in-store inventory and pricing.

Planned sources: Best Buy / Walmart / Target store-availability endpoints, Google Shopping
"nearby" results, Costco / Micro Center / Home Depot local stock, and grocery price feeds.
Returns offers with `distance_km` so the ranker can trade off price against the drive.
"""

from __future__ import annotations

from ...core.models import ProviderKind, Vertical
from ..base import NotYetImplementedProvider


class LocalStoreInventoryProvider(NotYetImplementedProvider):
    name = "local_inventory"
    kind = ProviderKind.LOCAL
    verticals = frozenset({Vertical.GOODS})
    description = "In-store stock and prices at shops near you (planned)"
    planned_approach = "retailer store-availability APIs + Google local results, keyed by postal code"
