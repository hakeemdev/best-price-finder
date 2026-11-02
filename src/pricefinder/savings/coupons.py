"""Coupon and promo-code sources.

`StaticCouponSource` reads `data/coupons.yaml`. Live sources (retailer promo feeds, community
code aggregators, browser-extension style auto-testing at checkout) implement the same class.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, UserProfile
from .base import SavingsSource, load_yaml, merchant_key


class StaticCouponSource(SavingsSource):
    name = "coupons.static"

    def __init__(self, path: str | None = None) -> None:
        self.path = path or get_settings().coupons_path
        self._data = load_yaml(self.path)

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        entries = self._data.get(merchant_key(offer), []) if isinstance(self._data, dict) else []
        out: list[Adjustment] = []
        now = datetime.now(UTC)
        for entry in entries:
            expires = entry.get("expires")
            if expires and datetime.fromisoformat(str(expires)).replace(tzinfo=UTC) < now:
                continue
            min_spend = Decimal(str(entry.get("min_spend", 0)))
            if offer.base_price.amount < min_spend:
                continue
            if entry.get("vertical") and entry["vertical"] != offer.vertical:
                continue
            amount = self._amount(entry, offer)
            if amount <= 0:
                continue
            out.append(
                Adjustment(
                    kind=AdjustmentKind.PROMO_CODE if entry.get("code") else AdjustmentKind.COUPON,
                    amount=Money(amount=amount, currency=offer.base_price.currency),
                    description=entry.get("description", "coupon"),
                    source=self.name,
                    code=entry.get("code"),
                    confidence=float(entry.get("confidence", 0.6)),
                    requires_action=entry.get("requires"),
                    metadata={"stackable": bool(entry.get("stackable", False))},
                )
            )
        return out

    @staticmethod
    def _amount(entry: dict, offer: Offer) -> Decimal:
        if "percent" in entry:
            pct = Decimal(str(entry["percent"])) / Decimal(100)
            amt = offer.base_price.amount * pct
            cap = entry.get("max")
            if cap is not None:
                amt = min(amt, Decimal(str(cap)))
            return amt.quantize(Decimal("0.01"))
        if "amount" in entry:
            return Decimal(str(entry["amount"]))
        if entry.get("free_shipping") and offer.shipping:
            return offer.shipping.amount
        return Decimal(0)
