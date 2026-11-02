from decimal import Decimal

from pricefinder.core.models import AdjustmentKind, Money, Offer, Query, Seller, SellerType, UserProfile, Vertical
from pricefinder.savings.rewards import CreditCardRewardsSource
from pricefinder.savings.signup import SignupBonusSource


def _offer(seller="Mock", price="200", vertical=Vertical.GOODS, stype=SellerType.RETAILER) -> Offer:
    return Offer(
        id="o",
        provider="mock",
        vertical=vertical,
        title="t",
        seller=Seller(name=seller, type=stype, merchant_id=seller.lower()),
        base_price=Money(amount=price),
    )


def test_best_card_chosen_for_goods(profile):
    src = CreditCardRewardsSource("data/cards.yaml")
    adjs = src.evaluate(_offer(), Query(raw="x", item="x"), profile)
    assert len(adjs) == 1
    adj = adjs[0]
    assert adj.kind == AdjustmentKind.CREDIT_CARD_REWARD
    # Citi Double Cash 2% on $200 = $4.00 beats Sapphire Preferred 1x @ 1.5c = $3.00
    assert adj.amount.amount == Decimal("4.00")
    assert adj.metadata["card_id"] == "citi_double_cash"


def test_travel_direct_booking_prefers_travel_multiplier(profile):
    src = CreditCardRewardsSource("data/cards.yaml")
    offer = _offer(seller="Delta", price="500", vertical=Vertical.FLIGHT, stype=SellerType.DIRECT)
    adjs = src.evaluate(offer, Query(raw="x", item="x", vertical=Vertical.FLIGHT), profile)
    # Sapphire Preferred 2x travel @ 1.5c = $15 beats Double Cash 2% = $10
    assert adjs[0].metadata["card_id"] == "chase_sapphire_preferred"
    assert adjs[0].amount.amount == Decimal("15.00")


def test_merchant_bonus_overrides_category():
    src = CreditCardRewardsSource("data/cards.yaml")
    p = UserProfile(id="p", cards=[{"card_id": "amazon_prime_visa"}])
    adjs = src.evaluate(_offer(seller="Amazon", price="100"), Query(raw="x", item="x"), p)
    assert adjs[0].amount.amount == Decimal("5.00")


def test_signup_bonus_surfaces_when_user_is_open_to_cards():
    src = CreditCardRewardsSource("data/cards.yaml")
    p = UserProfile(id="p", willing_to_open_cards=True)
    adjs = src.evaluate(
        _offer(price="2000", vertical=Vertical.HOTEL, stype=SellerType.DIRECT),
        Query(raw="x", item="x", vertical=Vertical.HOTEL),
        p,
    )
    kinds = {a.kind for a in adjs}
    assert AdjustmentKind.SIGNUP_BONUS in kinds
    assert all(a.confidence < 1 for a in adjs if a.kind == AdjustmentKind.SIGNUP_BONUS)


def test_quick_signup_offer_respects_profile_flag():
    src = SignupBonusSource("data/coupons.yaml")
    q = Query(raw="x", item="x")
    assert src.evaluate(_offer(), q, UserProfile(id="a", willing_to_sign_up=False)) == []
    adjs = src.evaluate(_offer(), q, UserProfile(id="b", willing_to_sign_up=True))
    assert adjs and adjs[0].amount.amount == Decimal("20.00")  # 10% of 200
