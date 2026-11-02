"""Savings modules: everything that lowers the *effective* price below the sticker price.

Each module implements `SavingsSource.evaluate(offer, query, profile) -> list[Adjustment]`.
The engine runs all of them and the ranker decides how much to trust each adjustment.
"""

from .base import SavingsSource
from .cashback import CashbackPortalSource
from .coupons import StaticCouponSource
from .membership import MembershipSource
from .rental_codes import RentalCodeSweepSource
from .rewards import CreditCardRewardsSource
from .signup import SignupBonusSource

__all__ = [
    "SavingsSource",
    "CashbackPortalSource",
    "StaticCouponSource",
    "CreditCardRewardsSource",
    "MembershipSource",
    "RentalCodeSweepSource",
    "SignupBonusSource",
]


def default_sources() -> list[SavingsSource]:
    """Every built-in savings source, in evaluation order."""
    return [
        StaticCouponSource(),
        SignupBonusSource(),
        RentalCodeSweepSource(),
        MembershipSource(),
        CashbackPortalSource(),
        CreditCardRewardsSource(),
    ]
