"""Quick-signup offers: newsletter / account / app first-purchase discounts and new-customer deals."""

from __future__ import annotations

from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, UserProfile
from .base import SavingsSource, load_yaml, merchant_key


class SignupBonusSource(SavingsSource):
    name = "signup.quick"

    def __init__(self, path: str | None = None) -> None:
        self._data = load_yaml(path or get_settings().coupons_path)

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        if not profile.willing_to_sign_up:
            return []
        signups = self._data.get("signup", {}) if isinstance(self._data, dict) else {}
        entry = signups.get(merchant_key(offer))
        if not entry:
            return []
        if "percent" in entry:
            value = offer.base_price.amount * Decimal(str(entry["percent"])) / Decimal(100)
            cap = entry.get("max")
            if cap is not None:
                value = min(value, Decimal(str(cap)))
        else:
            value = Decimal(str(entry.get("amount", 0)))
        value = value.quantize(Decimal("0.01"))
        if value <= 0:
            return []
        return [
            Adjustment(
                kind=AdjustmentKind.SIGNUP_BONUS,
                amount=Money(amount=value, currency=offer.base_price.currency),
                description=entry.get("description", "new-customer signup offer"),
                source=self.name,
                code=entry.get("code"),
                confidence=float(entry.get("confidence", 0.7)),
                requires_action=entry.get("requires", "create account / subscribe"),
            )
        ]
