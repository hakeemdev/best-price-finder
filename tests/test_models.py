from decimal import Decimal

import pytest

from pricefinder.core.models import Condition, Money, Offer, Seller, Vertical


def test_money_arithmetic_and_currency_guard():
    a = Money(amount="10.50")
    b = Money(amount=2)
    assert (a + b).amount == Decimal("12.50")
    assert (a - b).amount == Decimal("8.50")
    with pytest.raises(ValueError):
        a + Money(amount=1, currency="eur")


def test_sticker_total_sums_all_parts():
    o = Offer(
        id="x",
        provider="t",
        vertical=Vertical.GOODS,
        title="t",
        seller=Seller(name="s"),
        base_price=Money(amount=100),
        shipping=Money(amount=5),
        taxes=Money(amount="8.25"),
        fees=Money(amount=1),
        condition=Condition.NEW,
    )
    assert o.sticker_total.amount == Decimal("114.25")
