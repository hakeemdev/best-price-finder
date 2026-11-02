"""Credit card rewards valuation.

Given a user's cards (from `data/cards.yaml`) and an offer, compute the best card to pay with and
the dollar value of the points / cashback earned. Also surfaces signup bonuses on cards the user
does *not* hold, if the profile says they are open to applying.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config import get_settings
from ..core.models import Adjustment, AdjustmentKind, Money, Offer, Query, SellerType, UserProfile, Vertical
from .base import SavingsSource, load_yaml, merchant_key

# Spend categories that card catalogs use; an offer maps to one or more of these.
CATEGORY_BY_VERTICAL: dict[Vertical, tuple[str, ...]] = {
    Vertical.FLIGHT: ("airfare", "travel"),
    Vertical.HOTEL: ("hotels", "travel"),
    Vertical.CAR_RENTAL: ("car_rental", "travel"),
    Vertical.RESERVATION: ("dining", "entertainment"),
    Vertical.GOODS: ("online_shopping", "everything"),
    Vertical.SERVICE: ("everything",),
    Vertical.OTHER: ("everything",),
}


@dataclass
class CardCatalogEntry:
    id: str
    name: str
    issuer: str
    program: str
    point_value_cents: float
    earn: dict[str, float]  # category -> multiplier (points per dollar) or percent cashback
    merchant_bonus: dict[str, float]  # merchant_key -> multiplier (e.g. amazon: 5 for Prime Visa)
    signup_bonus_points: int = 0
    signup_bonus_min_spend: float = 0
    annual_fee: float = 0
    is_cashback: bool = False
    perks: list[str] | None = None


class CreditCardRewardsSource(SavingsSource):
    name = "rewards.credit_cards"

    def __init__(self, catalog_path: str | None = None) -> None:
        settings = get_settings()
        self.default_point_value = settings.default_point_value_cents
        raw = load_yaml(catalog_path or settings.cards_catalog_path)
        self.catalog: dict[str, CardCatalogEntry] = {}
        for cid, c in (raw.get("cards", {}) if isinstance(raw, dict) else {}).items():
            self.catalog[cid] = CardCatalogEntry(
                id=cid,
                name=c["name"],
                issuer=c.get("issuer", ""),
                program=c.get("program", cid),
                point_value_cents=float(c.get("point_value_cents", self.default_point_value)),
                earn={k: float(v) for k, v in (c.get("earn") or {}).items()},
                merchant_bonus={k: float(v) for k, v in (c.get("merchant_bonus") or {}).items()},
                signup_bonus_points=int(c.get("signup_bonus_points", 0)),
                signup_bonus_min_spend=float(c.get("signup_bonus_min_spend", 0)),
                annual_fee=float(c.get("annual_fee", 0)),
                is_cashback=bool(c.get("is_cashback", False)),
                perks=c.get("perks"),
            )

    # -- public ---------------------------------------------------------------

    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]:
        out: list[Adjustment] = []
        held = [self.catalog[h.card_id] for h in profile.cards if h.card_id in self.catalog]
        best = self.best_card(offer, held, profile)
        if best is not None:
            card, value = best
            if value > 0:
                out.append(
                    Adjustment(
                        kind=AdjustmentKind.CREDIT_CARD_REWARD,
                        amount=Money(amount=value, currency=offer.base_price.currency),
                        description=f"Pay with {card.name}: {self._describe_rate(card, offer)}",
                        source=self.name,
                        confidence=0.95,
                        metadata={"card_id": card.id, "program": card.program},
                    )
                )
        if profile.willing_to_open_cards:
            out.extend(self._signup_bonus_opportunities(offer, held, profile))
        return out

    def best_card(
        self, offer: Offer, held: list[CardCatalogEntry], profile: UserProfile
    ) -> tuple[CardCatalogEntry, Decimal] | None:
        best: tuple[CardCatalogEntry, Decimal] | None = None
        for card in held:
            value = self.reward_value(card, offer, profile)
            if best is None or value > best[1]:
                best = (card, value)
        return best

    def reward_value(self, card: CardCatalogEntry, offer: Offer, profile: UserProfile) -> Decimal:
        multiplier = self.multiplier(card, offer)
        spend = offer.sticker_total.amount
        if card.is_cashback:
            return (spend * Decimal(str(multiplier)) / Decimal(100)).quantize(Decimal("0.01"))
        cents = profile.point_values_cents.get(card.program, card.point_value_cents)
        points = spend * Decimal(str(multiplier))
        return (points * Decimal(str(cents)) / Decimal(100)).quantize(Decimal("0.01"))

    def multiplier(self, card: CardCatalogEntry, offer: Offer) -> float:
        mk = merchant_key(offer)
        if mk in card.merchant_bonus:
            return card.merchant_bonus[mk]
        categories = list(CATEGORY_BY_VERTICAL.get(offer.vertical, ("everything",)))
        if offer.vertical in (Vertical.FLIGHT, Vertical.HOTEL, Vertical.CAR_RENTAL):
            # Many cards pay more when booking direct vs through an OTA / portal.
            if offer.seller.type == SellerType.DIRECT:
                categories.insert(0, f"{categories[0]}_direct")
            elif offer.seller.type == SellerType.OTA:
                categories.insert(0, "travel_portal")
        for cat in categories:
            if cat in card.earn:
                return card.earn[cat]
        return card.earn.get("everything", 1.0)

    # -- internals ------------------------------------------------------------

    def _describe_rate(self, card: CardCatalogEntry, offer: Offer) -> str:
        m = self.multiplier(card, offer)
        return f"{m:g}% back" if card.is_cashback else f"{m:g}x {card.program} points"

    def _signup_bonus_opportunities(
        self, offer: Offer, held: list[CardCatalogEntry], profile: UserProfile
    ) -> list[Adjustment]:
        held_ids = {c.id for c in held}
        out: list[Adjustment] = []
        for card in self.catalog.values():
            if card.id in held_ids or card.signup_bonus_points <= 0:
                continue
            spend = offer.sticker_total.amount
            if spend < Decimal(str(card.signup_bonus_min_spend)) * Decimal("0.25"):
                continue  # purchase too small to meaningfully advance a min-spend requirement
            cents = profile.point_values_cents.get(card.program, card.point_value_cents)
            bonus_value = Decimal(card.signup_bonus_points) * Decimal(str(cents)) / Decimal(100)
            # Attribute the bonus proportionally to how much of the min spend this purchase covers.
            share = min(Decimal(1), spend / Decimal(str(card.signup_bonus_min_spend or 1)))
            value = (bonus_value * share - Decimal(str(card.annual_fee)) * share).quantize(Decimal("0.01"))
            if value <= 0:
                continue
            out.append(
                Adjustment(
                    kind=AdjustmentKind.SIGNUP_BONUS,
                    amount=Money(amount=value, currency=offer.base_price.currency),
                    description=(
                        f"Open {card.name}: {card.signup_bonus_points:,} pt bonus after "
                        f"${card.signup_bonus_min_spend:,.0f} spend (this purchase covers {share:.0%})"
                    ),
                    source=self.name,
                    confidence=0.4,
                    requires_action=f"apply for {card.name}",
                    metadata={"card_id": card.id, "annual_fee": card.annual_fee},
                )
            )
        return out
