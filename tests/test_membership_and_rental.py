from decimal import Decimal

from pricefinder.core.models import AdjustmentKind, Money, Offer, Query, Seller, SellerType, UserProfile, Vertical
from pricefinder.core.ranking import Ranker
from pricefinder.savings.membership import MembershipSource
from pricefinder.savings.rental_codes import RentalCodeSweepSource


def _rental(agency="Hertz", price="400") -> Offer:
    return Offer(
        id="r",
        provider="t",
        vertical=Vertical.CAR_RENTAL,
        title=f"{agency} midsize 5 days",
        seller=Seller(name=agency, type=SellerType.DIRECT, merchant_id=agency.lower()),
        base_price=Money(amount=price),
    )


def test_rental_codes_only_for_held_memberships_by_default():
    src = RentalCodeSweepSource("data/rental_codes.yaml")
    q = Query(raw="x", item="x", vertical=Vertical.CAR_RENTAL)
    none = src.evaluate(_rental(), q, UserProfile(id="a", willing_to_sign_up=False))
    assert none == []
    adjs = src.evaluate(_rental(), q, UserProfile(id="b", memberships=["AAA", "costco"], willing_to_sign_up=False))
    names = {a.description.split(" (")[0] for a in adjs}
    assert names == {"AAA member rate", "Costco Travel rate"}
    assert all(a.kind == AdjustmentKind.PROMO_CODE and a.requires_action is None for a in adjs)


def test_rental_codes_surface_quick_signup_loyalty_and_ranker_keeps_best():
    src = RentalCodeSweepSource("data/rental_codes.yaml")
    q = Query(raw="x", item="x", vertical=Vertical.CAR_RENTAL)
    adjs = src.evaluate(_rental(), q, UserProfile(id="c", memberships=["usaa"], willing_to_sign_up=True))
    kinds = {a.description.split(" (")[0] for a in adjs}
    assert "Hertz Gold Plus Rewards" in kinds and "USAA member rate" in kinds
    priced = Ranker().price(_rental(), adjs)
    assert len(priced.adjustments) == 1
    assert priced.adjustments[0].description.startswith("USAA")  # 20% of 400 beats 5%
    assert priced.adjustments[0].amount.amount == Decimal("80.00")


def test_rental_codes_ignore_non_rental_offers():
    src = RentalCodeSweepSource("data/rental_codes.yaml")
    goods = Offer(
        id="g",
        provider="t",
        vertical=Vertical.GOODS,
        title="t",
        seller=Seller(name="Hertz", merchant_id="hertz"),
        base_price=Money(amount=10),
    )
    assert src.evaluate(goods, Query(raw="x", item="x"), UserProfile(id="d", memberships=["aaa"])) == []


def test_membership_benefits_by_merchant_and_vertical():
    src = MembershipSource("data/memberships.yaml")
    hotel = Offer(
        id="h",
        provider="t",
        vertical=Vertical.HOTEL,
        title="Hyatt Place",
        seller=Seller(name="Hyatt", type=SellerType.DIRECT, merchant_id="hyatt"),
        base_price=Money(amount=300),
    )
    q = Query(raw="x", item="x", vertical=Vertical.HOTEL)
    adjs = src.evaluate(hotel, q, UserProfile(id="e", memberships=["aaa"], willing_to_sign_up=False))
    assert len(adjs) == 1 and adjs[0].kind == AdjustmentKind.MEMBERSHIP
    assert adjs[0].amount.amount == Decimal("30.00") and adjs[0].requires_action is None
    # Not a member, but open to quick signups: AAA (quick_signup) surfaces at reduced confidence; military does not.
    adjs = src.evaluate(hotel, q, UserProfile(id="f", willing_to_sign_up=True))
    assert [a.metadata["membership"] for a in adjs] == ["aaa", "aarp"]
    assert all(a.requires_action and a.confidence < 0.6 for a in adjs)
