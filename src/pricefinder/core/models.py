"""Domain models shared by every provider, savings module and storage backend.

Design goals:
- One `Query` shape expressive enough for goods, flights, hotels, car rentals and reservations.
- One `Offer` shape every provider emits, regardless of vertical.
- A `PricedOffer` that carries the full cost breakdown so a user can audit why something ranked first.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Vertical(StrEnum):
    GOODS = "goods"  # physical products, electronics, groceries, anything with a SKU
    FLIGHT = "flight"
    HOTEL = "hotel"
    CAR_RENTAL = "car_rental"
    RESERVATION = "reservation"  # restaurants, events, experiences, tickets
    SERVICE = "service"  # subscriptions, insurance, utilities, repairs
    OTHER = "other"


class Condition(StrEnum):
    NEW = "new"
    OPEN_BOX = "open_box"
    REFURBISHED = "refurbished"
    USED = "used"
    UNKNOWN = "unknown"


class SellerType(StrEnum):
    RETAILER = "retailer"  # Amazon, Best Buy, Walmart
    MARKETPLACE_INDIVIDUAL = "marketplace_individual"  # eBay / FB Marketplace / Craigslist person
    LOCAL_STORE = "local_store"  # physical store with in-stock inventory near you
    OTA = "ota"  # online travel agency: Expedia, Kayak, Priceline
    DIRECT = "direct"  # airline / hotel / rental agency direct
    RESELLER = "reseller"  # third-party reseller, ticket resale, refurbishers
    UNKNOWN = "unknown"


class ProviderKind(StrEnum):
    API = "api"  # official, keyed API
    SCRAPE = "scrape"  # HTML scraping
    BROWSER = "browser"  # headless browser automation
    LOCAL = "local"  # in-store / nearby inventory
    MOCK = "mock"


class AdjustmentKind(StrEnum):
    COUPON = "coupon"  # clip / auto-applied coupon
    PROMO_CODE = "promo_code"  # code entered at checkout
    CREDIT_CARD_REWARD = "credit_card_reward"  # points / cashback earned by paying with a card
    SIGNUP_BONUS = "signup_bonus"  # new-account or first-order bonus (store, app, newsletter)
    LOYALTY = "loyalty"  # airline / hotel / rental program benefit
    CASHBACK_PORTAL = "cashback_portal"  # Rakuten, TopCashback, etc.
    PRICE_MATCH = "price_match"  # retailer will match a lower price elsewhere
    MEMBERSHIP = "membership"  # Costco, Prime, AAA discounts
    STUDENT_OR_GROUP = "student_or_group"
    TAX = "tax"
    SHIPPING = "shipping"
    FEE = "fee"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class Money(BaseModel):
    amount: Decimal
    currency: str = "USD"

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Decimal:
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls(amount=Decimal("0"), currency=currency)

    def __str__(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


class Location(BaseModel):
    text: str | None = None  # free-form: "Austin, TX", "SFO", "near me"
    city: str | None = None
    region: str | None = None  # state / province
    country: str | None = None
    postal_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    radius_km: float | None = None
    iata: str | None = None  # airport code when relevant


class DateRange(BaseModel):
    start: date
    end: date | None = None
    flexible_days: int = 0  # +/- days the user is willing to shift

    @property
    def nights(self) -> int | None:
        if self.end is None:
            return None
        return (self.end - self.start).days


class Travelers(BaseModel):
    adults: int = 1
    children: int = 0
    infants: int = 0
    rooms: int = 1


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class Query(BaseModel):
    """A fully-specified search. Built by `QueryParser` from free text or constructed directly."""

    raw: str
    vertical: Vertical = Vertical.GOODS
    item: str  # normalized subject: "sony wh-1000xm5", "SFO->JFK", "Marriott Downtown Austin"
    brand: str | None = None
    model: str | None = None
    quantity: int = 1
    max_price: Money | None = None
    conditions: list[Condition] = Field(default_factory=list)  # empty = any
    currency: str = "USD"

    # Location: where the buyer is, or where the travel starts
    location: Location | None = None
    # Travel-specific
    origin: Location | None = None
    destination: Location | None = None
    dates: DateRange | None = None
    travelers: Travelers = Field(default_factory=Travelers)
    cabin: str | None = None  # economy / premium / business / first
    vehicle_class: str | None = None  # economy / suv / luxury
    pickup_time: time | None = None  # car rental / reservation local time
    dropoff_time: time | None = None
    one_way: bool = False

    include_used: bool = True
    include_local: bool = True
    include_online: bool = True
    max_drive_km: float | None = 50.0

    # Free-form extras a provider may use (e.g. {"color": "black", "storage": "256GB"})
    attributes: dict[str, Any] = Field(default_factory=dict)
    # Identifier of a stored user profile (cards, memberships) to apply savings for
    profile_id: str | None = None

    def cache_key(self) -> str:
        payload = self.model_dump_json(exclude={"raw"})
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


class Seller(BaseModel):
    name: str
    type: SellerType = SellerType.UNKNOWN
    url: str | None = None
    rating: float | None = None  # 0..5
    review_count: int | None = None
    location: Location | None = None
    merchant_id: str | None = None  # stable id used for coupon / cashback lookups


class Offer(BaseModel):
    """A single purchasable option as emitted by a provider. Prices are *sticker* prices."""

    id: str
    provider: str
    vertical: Vertical
    title: str
    url: str | None = None
    seller: Seller
    base_price: Money
    shipping: Money | None = None
    taxes: Money | None = None
    fees: Money | None = None  # resort fees, booking fees, young-driver fees, etc.
    condition: Condition = Condition.UNKNOWN
    in_stock: bool | None = None
    quantity_available: int | None = None
    location: Location | None = None  # pickup / store / property location
    distance_km: float | None = None
    image_url: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)  # upc, ean, asin, sku, mpn
    attributes: dict[str, Any] = Field(default_factory=dict)  # vertical-specific details
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] | None = Field(default=None, repr=False)

    @property
    def sticker_total(self) -> Money:
        total = self.base_price
        for part in (self.shipping, self.taxes, self.fees):
            if part is not None:
                total = total + part
        return total


class Adjustment(BaseModel):
    """A savings (negative) or extra cost (positive) applied on top of the sticker price."""

    kind: AdjustmentKind
    amount: Money  # positive = reduces effective price for savings; sign handled by `is_savings`
    description: str
    source: str  # which module / provider discovered it
    code: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # 1 = guaranteed, <1 = unverified
    requires_action: str | None = None  # e.g. "sign up for store account", "apply for card"
    is_savings: bool = True
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def signed_amount(self) -> Decimal:
        return -self.amount.amount if self.is_savings else self.amount.amount


class PricedOffer(BaseModel):
    """An offer after every applicable adjustment has been evaluated."""

    offer: Offer
    adjustments: list[Adjustment] = Field(default_factory=list)
    sticker_total: Money
    effective_total: Money
    guaranteed_total: Money  # only adjustments with confidence == 1.0
    score: float = 0.0  # ranking score, lower is better
    rank_reasons: list[str] = Field(default_factory=list)

    @property
    def total_savings(self) -> Money:
        return self.sticker_total - self.effective_total


class SearchResult(BaseModel):
    query: Query
    offers: list[PricedOffer]
    providers_queried: list[str]
    providers_failed: dict[str, str] = Field(default_factory=dict)
    started_at: datetime
    finished_at: datetime
    best_ever: Money | None = None  # lowest recorded historical effective price for this item

    @property
    def best(self) -> PricedOffer | None:
        return self.offers[0] if self.offers else None


# ---------------------------------------------------------------------------
# User profile (drives rewards / loyalty / membership adjustments)
# ---------------------------------------------------------------------------


class CardHolding(BaseModel):
    card_id: str  # key into data/cards.yaml
    nickname: str | None = None


class LoyaltyMembership(BaseModel):
    program: str  # e.g. "marriott_bonvoy", "delta_skymiles", "hertz_gold"
    tier: str | None = None
    member_id_hint: str | None = None


class UserProfile(BaseModel):
    id: str = "default"
    cards: list[CardHolding] = Field(default_factory=list)
    loyalty: list[LoyaltyMembership] = Field(default_factory=list)
    memberships: list[str] = Field(default_factory=list)  # costco, prime, aaa, student
    home: Location | None = None
    willing_to_sign_up: bool = True  # consider quick signups (newsletters, store accounts)
    willing_to_open_cards: bool = False  # consider credit card signup bonuses
    point_values_cents: dict[str, float] = Field(default_factory=dict)  # override per program
    currency: str = "USD"
