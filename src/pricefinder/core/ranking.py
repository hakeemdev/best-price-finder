"""Compute effective prices and rank offers.

Effective price = sticker total (base + shipping + tax + fees) minus every savings adjustment.
Guaranteed price only counts adjustments with confidence 1.0 (e.g. tax, shipping, verified coupon).
The ranking score blends the expected effective price with soft penalties so a sketchy
marketplace listing 60 km away doesn't beat a reputable retailer by $2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import Adjustment, AdjustmentKind, Condition, Money, Offer, PricedOffer, Query, SellerType


@dataclass
class RankingWeights:
    # Dollar-equivalent penalties
    per_km_distance: float = 0.15  # cost of driving: fuel + time
    unknown_stock: float = 5.0
    out_of_stock: float = 1e6
    low_rating: float = 10.0  # applied when seller rating < 4.0
    individual_seller: float = 8.0  # friction/risk premium for person-to-person deals
    used_condition: float = 0.0  # user chose to include used; no penalty by default
    unverified_adjustment_discount: float = 1.0  # multiply uncertain savings by confidence
    # Stack rules
    allow_multiple_promo_codes: bool = False


class Ranker:
    def __init__(self, weights: RankingWeights | None = None) -> None:
        self.w = weights or RankingWeights()

    def price(self, offer: Offer, adjustments: list[Adjustment]) -> PricedOffer:
        adjustments = self._dedupe_stack(adjustments)
        sticker = offer.sticker_total
        currency = sticker.currency
        expected = sticker.amount
        guaranteed = sticker.amount
        for adj in adjustments:
            amt = adj.signed_amount
            if adj.is_savings:
                expected += amt * Decimal(str(adj.confidence))
                if adj.confidence >= 1.0:
                    guaranteed += amt
            else:
                expected += amt
                guaranteed += amt
        expected = max(expected, Decimal(0)).quantize(Decimal("0.01"))
        guaranteed = max(guaranteed, Decimal(0)).quantize(Decimal("0.01"))
        return PricedOffer(
            offer=offer,
            adjustments=adjustments,
            sticker_total=sticker,
            effective_total=Money(amount=expected, currency=currency),
            guaranteed_total=Money(amount=guaranteed, currency=currency),
        )

    def score(self, po: PricedOffer, query: Query) -> PricedOffer:
        w = self.w
        score = float(po.effective_total.amount)
        reasons: list[str] = []
        o = po.offer
        if o.in_stock is False:
            score += w.out_of_stock
            reasons.append("out of stock")
        elif o.in_stock is None:
            score += w.unknown_stock
        if o.distance_km:
            penalty = o.distance_km * w.per_km_distance
            score += penalty
            reasons.append(f"{o.distance_km:.0f} km away (+${penalty:.2f} travel)")
        if o.seller.rating is not None and o.seller.rating < 4.0:
            score += w.low_rating
            reasons.append(f"seller rating {o.seller.rating:.1f}")
        if o.seller.type == SellerType.MARKETPLACE_INDIVIDUAL:
            score += w.individual_seller
            reasons.append("individual seller")
        if o.condition in (Condition.USED, Condition.REFURBISHED, Condition.OPEN_BOX):
            score += w.used_condition
            reasons.append(o.condition.value.replace("_", " "))
        if query.max_price and po.effective_total.amount > query.max_price.amount:
            reasons.append("over budget")
        po.score = round(score, 2)
        po.rank_reasons = reasons
        return po

    def rank(self, priced: list[PricedOffer], query: Query) -> list[PricedOffer]:
        scored = [self.score(p, query) for p in priced]
        return sorted(scored, key=lambda p: (p.score, p.effective_total.amount, p.sticker_total.amount))

    def _dedupe_stack(self, adjustments: list[Adjustment]) -> list[Adjustment]:
        """Apply stacking rules: one promo code unless stackable, one card reward, one portal."""
        out: list[Adjustment] = []
        best_single: dict[AdjustmentKind, Adjustment] = {}
        for adj in adjustments:
            single_kinds = {
                AdjustmentKind.CREDIT_CARD_REWARD,
                AdjustmentKind.CASHBACK_PORTAL,
                AdjustmentKind.SIGNUP_BONUS,
            }
            if (
                adj.kind == AdjustmentKind.PROMO_CODE
                and not self.w.allow_multiple_promo_codes
                and not adj.metadata.get("stackable")
            ):
                single_kinds.add(AdjustmentKind.PROMO_CODE)
            if adj.kind in single_kinds:
                cur = best_single.get(adj.kind)
                if cur is None or adj.amount.amount * Decimal(str(adj.confidence)) > cur.amount.amount * Decimal(
                    str(cur.confidence)
                ):
                    best_single[adj.kind] = adj
            else:
                out.append(adj)
        out.extend(best_single.values())
        return out
