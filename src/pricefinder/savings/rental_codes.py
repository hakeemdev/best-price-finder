"""Car-rental discount-code sweep.

Agencies accept exactly one discount code per rental (Hertz CDP, Avis AWD, Budget BCD, Enterprise
customer number, etc.). Membership rates (AAA, Costco, USAA, AARP, corporate) are often 10-35% off
the walk-up rate. This source enumerates every code the user is eligible for and emits each as a
non-stackable promo code; the ranker keeps the single best one per offer.
"""

from __future__ import annotations

from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, UserProfile, Vertical
from .base import SavingsSource, load_yaml, merchant_key

_NO_MEMBERSHIP = {"none", None, ""}
_QUICK_JOIN = {"loyalty"}  # free programs anyone can join in a minute


class RentalCodeSweepSource(SavingsSource):
    name = "rental.code_sweep"

    def __init__(self, path: str | None = None) -> None:
        self._data = load_yaml(path or get_settings().rental_codes_path)

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        if offer.vertical != Vertical.CAR_RENTAL:
            return []
        agencies = self._data.get("agencies", {}) if isinstance(self._data, dict) else {}
        codes = agencies.get(merchant_key(offer), [])
        held = {m.lower() for m in profile.memberships}
        out: list[Adjustment] = []
        for entry in codes:
            membership = (entry.get("requires_membership") or "").lower() or None
            eligible = membership in _NO_MEMBERSHIP or membership in held
            quick = membership in _QUICK_JOIN or bool(entry.get("quick_signup"))
            if not eligible and not (profile.willing_to_sign_up and quick):
                continue
            pct = Decimal(str(entry.get("percent", 0)))
            value = (offer.base_price.amount * pct / Decimal(100)).quantize(Decimal("0.01"))
            if value <= 0:
                continue
            confidence = float(entry.get("confidence", 0.5))
            if membership and membership not in held:
                confidence *= 0.7  # user must still join
            out.append(
                Adjustment(
                    kind=AdjustmentKind.PROMO_CODE,
                    amount=Money(amount=value, currency=offer.base_price.currency),
                    description=f"{entry.get('name', 'discount code')} (~{pct:g}% off)",
                    source=self.name,
                    code=entry.get("code"),
                    confidence=confidence,
                    requires_action=(
                        f"{membership.upper()} membership" if membership and membership not in held else None
                    ),
                    metadata={"stackable": False, "membership": membership, "code_type": entry.get("code_type")},
                )
            )
        return out
