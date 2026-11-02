from decimal import Decimal

from pricefinder.core.models import Adjustment, AdjustmentKind, Money, Offer, Query, Seller, SellerType, Vertical
from pricefinder.core.ranking import Ranker


def _offer(price: str, **kw) -> Offer:
    return Offer(
        id=kw.pop("id", "o"),
        provider="t",
        vertical=Vertical.GOODS,
        title="thing",
        seller=kw.pop("seller", Seller(name="s")),
        base_price=Money(amount=price),
        **kw,
    )


def test_effective_price_weights_uncertain_savings():
    r = Ranker()
    po = r.price(
        _offer("100"),
        [
            Adjustment(
                kind=AdjustmentKind.COUPON, amount=Money(amount=10), description="sure", source="t", confidence=1.0
            ),
            Adjustment(
                kind=AdjustmentKind.PROMO_CODE, amount=Money(amount=20), description="maybe", source="t", confidence=0.5
            ),
        ],
    )
    assert po.sticker_total.amount == Decimal("100")
    assert po.effective_total.amount == Decimal("80.00")  # 100 - 10 - 20*0.5
    assert po.guaranteed_total.amount == Decimal("90.00")


def test_only_best_card_reward_is_kept():
    r = Ranker()
    adjs = [
        Adjustment(kind=AdjustmentKind.CREDIT_CARD_REWARD, amount=Money(amount=2), description="a", source="t"),
        Adjustment(kind=AdjustmentKind.CREDIT_CARD_REWARD, amount=Money(amount=5), description="b", source="t"),
    ]
    po = r.price(_offer("100"), adjs)
    assert len(po.adjustments) == 1 and po.adjustments[0].description == "b"


def test_rank_penalizes_distance_and_individual_sellers():
    r = Ranker()
    q = Query(raw="x", item="x")
    cheap_far = r.price(
        _offer("90", id="far", seller=Seller(name="p", type=SellerType.MARKETPLACE_INDIVIDUAL), distance_km=80), []
    )
    retail = r.price(_offer("100", id="retail", seller=Seller(name="r", type=SellerType.RETAILER), in_stock=True), [])
    ranked = r.rank([cheap_far, retail], q)
    assert ranked[0].offer.id == "retail"
    assert any("km away" in s for s in ranked[1].rank_reasons)
