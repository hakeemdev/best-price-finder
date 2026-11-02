"""Membership and group discounts: Costco, AAA, AARP, Prime, student, military, corporate.

Reads `data/memberships.yaml`: membership -> merchant key -> benefit. Applies benefits for
memberships the user holds; also surfaces benefits behind memberships the user could join quickly
(flagged `quick_signup: true`) at reduced confidence when the profile allows signups.
"""

from __future__ import annotations

from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, UserProfile
from .base import SavingsSource, load_yaml, merchant_key


class MembershipSource(SavingsSource):
    name = "membership.benefits"

    def __init__(self, path: str | None = None) -> None:
        self._data = load_yaml(path or get_settings().memberships_path)

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        memberships = self._data.get("memberships", {}) if isinstance(self._data, dict) else {}
        held = {m.lower() for m in profile.memberships}
        mk = merchant_key(offer)
        out: list[Adjustment] = []
        for name, spec in memberships.items():
            benefits = spec.get("benefits", {})
            benefit = benefits.get(mk) or benefits.get(f"vertical:{offer.vertical.value}")
            if not benefit:
                continue
            is_held = name.lower() in held
            if not is_held and not (profile.willing_to_sign_up and spec.get("quick_signup")):
                continue
            value = self._value(benefit, offer)
            if value <= 0:
                continue
            confidence = float(benefit.get("confidence", 0.8)) * (1.0 if is_held else 0.6)
            out.append(
                Adjustment(
                    kind=AdjustmentKind.MEMBERSHIP,
                    amount=Money(amount=value, currency=offer.base_price.currency),
                    description=f"{spec.get('name', name)}: {benefit.get('description', 'member discount')}",
                    source=self.name,
                    code=benefit.get("code"),
                    confidence=confidence,
                    requires_action=None if is_held else f"join {spec.get('name', name)}",
                    metadata={"membership": name},
                )
            )
        return out

    @staticmethod
    def _value(benefit: dict, offer: Offer) -> Decimal:
        if "percent" in benefit:
            v = offer.base_price.amount * Decimal(str(benefit["percent"])) / Decimal(100)
            if benefit.get("max") is not None:
                v = min(v, Decimal(str(benefit["max"])))
            return v.quantize(Decimal("0.01"))
        if "amount" in benefit:
            return Decimal(str(benefit["amount"]))
        if benefit.get("free_shipping") and offer.shipping:
            return offer.shipping.amount
        return Decimal(0)
