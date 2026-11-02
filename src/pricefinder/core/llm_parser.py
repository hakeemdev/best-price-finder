"""LLM-backed query understanding using the Anthropic SDK (`pricefinder[llm]`).

Handles what the rule-based parser cannot: messy phrasing, implied verticals, spelled-out dates,
multi-constraint requests ("a 65 inch oled tv under 1500 that I can pick up today"). The rule-based
parser always runs first; the LLM refines it, and any failure falls back to the rules result.
"""

from __future__ import annotations

import logging
from datetime import date, time
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from .models import Condition, DateRange, Location, Money, Query, Travelers, Vertical
from .query import QueryParser, RuleBasedQueryParser

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You turn a shopper's free-text request into a structured search query for a price-comparison engine.

Rules:
- Pick exactly one vertical: goods (physical products), flight, hotel (incl. vacation rentals),
  car_rental, reservation (restaurants, tickets, events, experiences), service (subscriptions,
  plans, insurance), or other.
- `item` is the normalized subject only: product name with brand/model, a route like "SFO -> JFK",
  a hotel/city, or a vehicle class. Strip words like "cheapest", "best price", budgets, locations
  and dates.
- Dates are ISO (YYYY-MM-DD). Resolve relative dates against the given today date. If only a
  start date is known leave end_date null. Pickup/drop-off clock times go in pickup_time /
  dropoff_time as HH:MM (24h).
- Airports: use IATA codes when the user gives one or the city has one obvious major airport;
  otherwise the city name.
- Conditions: only set when the user states a preference (new, used, refurbished, open_box).
- Budget: max_price is the numeric ceiling in the user's currency, else null.
- Do not invent constraints the user did not state. Leave fields null when unknown."""


class ParsedQuery(BaseModel):
    vertical: Literal["goods", "flight", "hotel", "car_rental", "reservation", "service", "other"]
    item: str
    brand: str | None = None
    model: str | None = None
    quantity: int = 1
    max_price: float | None = None
    currency: str = "USD"
    conditions: list[Literal["new", "open_box", "refurbished", "used"]] = Field(default_factory=list)
    location_text: str | None = None
    origin_text: str | None = None
    origin_iata: str | None = None
    destination_text: str | None = None
    destination_iata: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    pickup_time: time | None = None
    dropoff_time: time | None = None
    flexible_days: int = 0
    adults: int = 1
    children: int = 0
    rooms: int = 1
    cabin: Literal["economy", "premium economy", "business", "first"] | None = None
    vehicle_class: str | None = None
    one_way: bool = False
    wants_pickup_today: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)


class LLMQueryParser:
    """Anthropic-backed parser with rule-based fallback. Inject `client` for tests."""

    def __init__(
        self, settings: Settings | None = None, *, client: Any | None = None, model: str | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.model = model or self.settings.llm_model
        self.rules = RuleBasedQueryParser()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so the core package has no hard dependency

            kwargs: dict[str, Any] = {"max_retries": 2, "timeout": 30.0}
            if self.settings.anthropic_api_key:
                kwargs["api_key"] = self.settings.anthropic_api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def parse(self, text: str, *, today: date | None = None) -> Query:
        today = today or date.today()
        base = self.rules.parse(text, today=today)
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=2048,
                system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": f"Today is {today.isoformat()}.\n\nRequest: {text}"}],
                output_format=ParsedQuery,
            )
        except Exception as exc:  # noqa: BLE001 - network/auth/refusal: rules result is still useful
            log.warning("LLM parser failed, using rule-based result: %s", exc)
            return base
        if getattr(response, "stop_reason", None) == "refusal" or response.parsed_output is None:
            log.warning(
                "LLM parser returned no structured output (stop_reason=%s)", getattr(response, "stop_reason", None)
            )
            return base
        return self.merge(base, response.parsed_output)

    @staticmethod
    def merge(base: Query, p: ParsedQuery) -> Query:
        q = base.model_copy(deep=True)
        q.vertical = Vertical(p.vertical)
        q.item = p.item.strip() or base.item
        q.brand, q.model = p.brand, p.model
        q.quantity = max(1, p.quantity)
        q.currency = p.currency.upper() if p.currency else base.currency
        if p.max_price is not None:
            q.max_price = Money(amount=Decimal(str(p.max_price)), currency=q.currency)
        if p.conditions:
            q.conditions = [Condition(c) for c in p.conditions]
            q.include_used = Condition.USED in q.conditions or Condition.REFURBISHED in q.conditions
        if p.location_text:
            q.location = Location(text=p.location_text)
        if p.origin_text or p.origin_iata:
            q.origin = Location(text=p.origin_text or p.origin_iata, iata=(p.origin_iata or "").upper() or None)
        if p.destination_text or p.destination_iata:
            q.destination = Location(
                text=p.destination_text or p.destination_iata, iata=(p.destination_iata or "").upper() or None
            )
            if q.vertical in (Vertical.HOTEL, Vertical.CAR_RENTAL, Vertical.RESERVATION) and q.location is None:
                q.location = q.destination
        if p.start_date:
            q.dates = DateRange(start=p.start_date, end=p.end_date, flexible_days=p.flexible_days)
        q.pickup_time = p.pickup_time or q.pickup_time
        q.dropoff_time = p.dropoff_time or q.dropoff_time
        q.travelers = Travelers(adults=max(1, p.adults), children=max(0, p.children), rooms=max(1, p.rooms))
        q.cabin = p.cabin or q.cabin
        q.vehicle_class = p.vehicle_class or q.vehicle_class
        q.one_way = p.one_way or q.one_way
        if p.wants_pickup_today:
            q.include_online = False
            q.attributes["pickup_today"] = True
        q.attributes.update(p.attributes)
        return q


def build_parser(settings: Settings | None = None) -> QueryParser:
    """Pick the parser from settings: rules, llm, or auto (llm when a key is available)."""
    import os

    settings = settings or get_settings()
    mode = settings.query_parser
    has_key = bool(settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))
    if mode == "llm" or (mode == "auto" and has_key):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            log.warning("query_parser=%s but the `anthropic` package is missing; install pricefinder[llm]", mode)
            return RuleBasedQueryParser()
        return LLMQueryParser(settings)
    return RuleBasedQueryParser()
