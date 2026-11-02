"""Turn free text into a structured `Query`.

The default parser is rule-based so it works offline with zero keys. An LLM-backed parser can
implement the same `QueryParser` protocol and be swapped in via `SearchEngine(parser=...)`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from dateutil import parser as dateparser

from .models import Condition, DateRange, Location, Money, Query, Travelers, Vertical

_IATA = re.compile(r"\b([A-Z]{3})\b")
_ROUTE = re.compile(
    r"(?:flights?|fly|flying|airfare)\s+(?:from\s+)?(?P<origin>[A-Za-z .]+?)\s+(?:to|->|-)\s+"
    r"(?P<dest>[A-Za-z .]+?)(?:\s+(?:on|in|for|from|leaving|departing|returning|round|one)\b|$|,)",
    re.IGNORECASE,
)
_PRICE = re.compile(r"(?:under|below|less than|max|<=?)\s*\$?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_NEAR = re.compile(
    r"\b(?:near|in|around|within)\s+(?P<loc>[A-Za-z0-9 ,.]+?)(?:\s+(?:under|below|for|on|from)\b|$)", re.IGNORECASE
)
_QTY = re.compile(r"\b(\d+)\s*x\b|\bx\s*(\d+)\b", re.IGNORECASE)
_NOISE_WORDS = re.compile(
    r"\b(best price for|cheapest|price of|buy|find|deal on|deals on|rental cars?|car rentals?|rent a car|"
    r"hotels? in|hotels?|flights?|airfare|reservation for|for \d+ (?:adults?|people|nights?|days?)|"
    r"\d+ (?:adults?|rooms?|kids?|children|nights?))\b",
    re.IGNORECASE,
)
_DATE_TOKEN = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b"
    r"|\b(?:next weekend|this weekend|tomorrow)\b",
    re.IGNORECASE,
)

_VERTICAL_HINTS: dict[Vertical, tuple[str, ...]] = {
    Vertical.FLIGHT: ("flight", "flights", "airfare", "fly to", "flying to", "plane ticket", "round trip", "one way"),
    Vertical.HOTEL: ("hotel", "hotels", "motel", "resort", "airbnb", "vrbo", "stay in", "room for", "nights in"),
    Vertical.CAR_RENTAL: (
        "rental car",
        "car rental",
        "rent a car",
        "hertz",
        "avis",
        "enterprise",
        "turo",
        "suv rental",
    ),
    Vertical.RESERVATION: (
        "reservation",
        "table for",
        "tickets to",
        "concert",
        "show tickets",
        "tee time",
        "experience",
    ),
    Vertical.SERVICE: ("subscription", "insurance", "internet plan", "phone plan", "gym membership"),
}

_CONDITION_HINTS: dict[Condition, tuple[str, ...]] = {
    Condition.NEW: ("brand new", "new only", "sealed"),
    Condition.USED: ("used", "second hand", "pre-owned", "preowned"),
    Condition.REFURBISHED: ("refurbished", "refurb", "renewed"),
    Condition.OPEN_BOX: ("open box", "open-box"),
}


class QueryParser(Protocol):
    def parse(self, text: str, *, today: date | None = None) -> Query: ...


class RuleBasedQueryParser:
    """Cheap, deterministic parser. Good enough to route to the right providers."""

    def parse(self, text: str, *, today: date | None = None) -> Query:
        today = today or date.today()
        lowered = text.lower()
        vertical = self._detect_vertical(lowered)
        q = Query(raw=text, vertical=vertical, item=text.strip())

        if m := _PRICE.search(text):
            q.max_price = Money(amount=Decimal(m.group(1)))
        if m := _QTY.search(text):
            q.quantity = int(m.group(1) or m.group(2))

        conds = [c for c, hints in _CONDITION_HINTS.items() if any(h in lowered for h in hints)]
        if conds:
            q.conditions = conds
            q.include_used = Condition.USED in conds or Condition.REFURBISHED in conds

        if vertical == Vertical.FLIGHT:
            self._parse_flight(q, text)
        elif vertical in (Vertical.HOTEL, Vertical.CAR_RENTAL, Vertical.RESERVATION):
            self._parse_stay(q, text)
        else:
            if m := _NEAR.search(text):
                q.location = self._loc(m.group("loc"))
            q.item = self._clean_item(text)

        q.dates = q.dates or self._parse_dates(text, today)
        q.one_way = "one way" in lowered or "one-way" in lowered
        for cabin in ("first", "business", "premium economy", "economy"):
            if cabin in lowered:
                q.cabin = cabin
                break
        q.travelers = self._parse_travelers(lowered)
        return q

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _detect_vertical(lowered: str) -> Vertical:
        for vertical, hints in _VERTICAL_HINTS.items():
            if any(h in lowered for h in hints):
                return vertical
        return Vertical.GOODS

    @staticmethod
    def _clean_item(text: str) -> str:
        cleaned = _DATE_TOKEN.sub("", text)
        cleaned = _PRICE.sub("", cleaned)
        cleaned = _NEAR.sub("", cleaned)
        cleaned = _QTY.sub("", cleaned)
        for hints in _CONDITION_HINTS.values():
            for h in hints:
                cleaned = re.sub(rf"\b{re.escape(h)}\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = _NOISE_WORDS.sub("", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(" ,.-")

    def _parse_flight(self, q: Query, text: str) -> None:
        if m := _ROUTE.search(text):
            q.origin = self._loc(m.group("origin"))
            q.destination = self._loc(m.group("dest"))
        else:
            codes = _IATA.findall(text)
            if len(codes) >= 2:
                q.origin, q.destination = self._loc(codes[0]), self._loc(codes[1])
        if q.origin and q.destination:
            q.item = f"{q.origin.iata or q.origin.text} -> {q.destination.iata or q.destination.text}"

    def _parse_stay(self, q: Query, text: str) -> None:
        if m := _NEAR.search(text):
            q.destination = self._loc(m.group("loc"))
            q.location = q.destination
        q.item = self._clean_item(text)
        if q.destination and (not q.item or q.item.lower() in ("in", "to", "near")):
            q.item = q.destination.text or ""
        for cls in ("economy", "compact", "midsize", "suv", "luxury", "van", "truck", "convertible"):
            if re.search(rf"\b{cls}\b", text, re.IGNORECASE):
                q.vehicle_class = cls
                break

    @staticmethod
    def _loc(raw: str) -> Location:
        raw = re.sub(r"\s+", " ", _NOISE_WORDS.sub("", _DATE_TOKEN.sub("", raw))).strip(" ,.-")
        iata = raw.upper() if re.fullmatch(r"[A-Za-z]{3}", raw) else None
        return Location(text=raw, iata=iata)

    @staticmethod
    def _parse_dates(text: str, today: date) -> DateRange | None:
        lowered = text.lower()
        if "next weekend" in lowered:
            days_ahead = (5 - today.weekday()) % 7 + 7
            start = today + timedelta(days=days_ahead)
            return DateRange(start=start, end=start + timedelta(days=2))
        if "this weekend" in lowered:
            start = today + timedelta(days=(5 - today.weekday()) % 7)
            return DateRange(start=start, end=start + timedelta(days=2))
        if "tomorrow" in lowered:
            return DateRange(start=today + timedelta(days=1))

        found: list[date] = []
        for m in re.finditer(
            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
            r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b",
            text,
            re.IGNORECASE,
        ):
            try:
                d = dateparser.parse(m.group(0), default=datetime(today.year, today.month, 1)).date()
            except (ValueError, OverflowError):
                continue
            if d < today and m.group(0)[-4:].isdigit() is False:
                d = d.replace(year=today.year + 1)
            found.append(d)
        if not found:
            return None
        found.sort()
        end = found[1] if len(found) > 1 else None
        flexible = 3 if "flexible" in lowered else 0
        return DateRange(start=found[0], end=end, flexible_days=flexible)

    @staticmethod
    def _parse_travelers(lowered: str) -> Travelers:
        t = Travelers()
        if (m := re.search(r"(\d+)\s+adults?", lowered)) or (m := re.search(r"\b(?:for|party of)\s+(\d+)\b", lowered)):
            t.adults = int(m.group(1))
        if m := re.search(r"(\d+)\s+(?:kids?|children)", lowered):
            t.children = int(m.group(1))
        if m := re.search(r"(\d+)\s+rooms?", lowered):
            t.rooms = int(m.group(1))
        return t
