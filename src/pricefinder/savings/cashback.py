"""Shopping-portal cashback (Rakuten, TopCashback, airline/hotel shopping portals)."""

from __future__ import annotations

from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, UserProfile
from .base import SavingsSource, load_yaml, merchant_key


class CashbackPortalSource(SavingsSource):
    name = "cashback.portals"

    def __init__(self, path: str | None = None) -> None:
        self._data = load_yaml(path or get_settings().cashback_portals_path)

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        portals = self._data.get("portals", {}) if isinstance(self._data, dict) else {}
        mk = merchant_key(offer)
        best: Adjustment | None = None
        for portal, merchants in portals.items():
            rate = merchants.get(mk)
            if rate is None:
                continue
            value = (offer.base_price.amount * Decimal(str(rate)) / Decimal(100)).quantize(Decimal("0.01"))
            adj = Adjustment(
                kind=AdjustmentKind.CASHBACK_PORTAL,
                amount=Money(amount=value, currency=offer.base_price.currency),
                description=f"{rate:g}% back via {portal}",
                source=self.name,
                confidence=0.8,
                requires_action=f"start purchase from {portal}",
                metadata={"portal": portal, "rate": rate},
            )
            if best is None or adj.amount.amount > best.amount.amount:
                best = adj
        return [best] if best else []
