"""Nearby in-store inventory and pricing (aggregator slot).

Best Buy in-store stock is already live inside the `bestbuy` provider. This slot is reserved for
sources that only report local availability: Target / Walmart store stock, Costco warehouse pricing,
Micro Center, Home Depot / Lowe's, grocery price feeds, and Google "nearby" shopping results.
Returns offers with `distance_km` so the ranker can trade off price against the drive.
"""

from __future__ import annotations

from ...core.models import ProviderKind, Vertical
from ..base import NotYetImplementedProvider


class LocalStoreInventoryProvider(NotYetImplementedProvider):
    name = "local_inventory"
    kind = ProviderKind.LOCAL
    verticals = frozenset({Vertical.GOODS})
    description = "Store-only stock near you: Target, Costco, Micro Center, Home Depot (planned)"
    planned_approach = "retailer store-availability endpoints + Google local results, keyed by postal code"
