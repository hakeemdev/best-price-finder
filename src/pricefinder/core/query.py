"""Turn free text into a structured `Query`.

The default parser is rule-based so it works offline with zero keys. An LLM-backed parser can
implement the same `QueryParser` protocol and be swapped in via `SearchEngine(parser=...)`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
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
    r"\b(?:near|in|around|within|from|at)\s+(?P<loc>[A-Za-z][A-Za-z0-9 ,.]*?)"
    r"(?:\s+(?:under|below|for|on|from|to|at|starting|pickup|pick up|drop ?off)\b|$|,(?=\s*\d))",
    re.IGNORECASE,
)
_AIRPORT_PICKUP = re.compile(
    r"\b(?:at|in|on|from)[- ]the[- ]airport\b|\bin[- ]terminal\b|\bon[- ]airport\b"
    r"|\bairport (?:pickup|pick-up|counter|terminal)\b",
    re.IGNORECASE,
)
_TIME_TOKEN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[ap]m)", re.IGNORECASE
)
_QTY = re.compile(r"\b(\d+)\s*x\b|\bx\s*(\d+)\b", re.IGNORECASE)
_NOISE_WORDS = re.compile(
    r"\b(best price for|cheapest|price of|buy|find|deal on|deals on|rental cars?|car rentals?|rent a car|rent an?|rent|"
    r"hotels? in|hotels?|flights?|airfare|reservation for|for \d+ (?:adults?|people|nights?|days?)|"
    r"\d+ (?:adults?|rooms?|kids?|children|nights?))\b",
    re.IGNORECASE,
)
_DANGLING = re.compile(
    r"^(?:(?:to|from|at|in|on|for|and|a|an|the)\s+)+|(?:\s+(?:to|from|at|in|on|for|and|a|an|the))+$", re.IGNORECASE
)
_CLASS_WORDS = re.compile(
    r"\b(?:economy|compact|mid-?size|intermediate|standard|full-?size|suv|luxury|premium|mini-?van|van|"
    r"pickup truck|truck|convertible)\b",
    re.IGNORECASE,
)
_MAKES = re.compile(
    r"\b(?:toyota|honda|nissan|hyundai|kia|ford|chevrolet|chevy|gmc|jeep|dodge|chrysler|ram|mazda|subaru|volkswagen|vw|"
    r"bmw|mercedes|audi|lexus|tesla|mini|mitsubishi|buick|cadillac|lincoln|volvo|infiniti|acura|genesis|porsche|"
    r"jaguar|land rover|range rover|fiat|alfa romeo|polestar|rivian)\b",
    re.IGNORECASE,
)
# Well-known models -> rental class, matched on a squashed ("rav 4" == "rav4") lowercase query. Names that are
# also places or common words (Tahoe, Taos, Kona, Colorado, Explorer, ...) are deliberately left out.
_MODEL_CLASSES: dict[str, str] = {
    "suv": (
        "rav4 crv hrv rogue murano pathfinder armada cx5 cx30 cx50 cx9 cx90 equinox traverse blazer trailblazer "
        "tucson palisade sportage sorento telluride seltos tiguan bronco highlander 4runner sequoia corollacross "
        "venza landcruiser forester crosstrek wrangler renegade countryman bmwx1 bmwx3 bmwx5 audiq5 audiq7"
    ),
    "van": "sienna odyssey pacifica sprinter",
    "truck": "f150 f250 silverado tundra ram1500 maverick gladiator",
}
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
        "rent a ",
        "rent an ",
        "hertz",
        "avis",
        "enterprise",
        "sixt",
        "alamo",
        "thrifty",
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
        q.pickup_time, q.dropoff_time = self._parse_times(text)
        if _AIRPORT_PICKUP.search(text):
            q.attributes["airport_pickup"] = True
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
        cleaned = _AIRPORT_PICKUP.sub("", cleaned)
        cleaned = _TIME_TOKEN.sub("", cleaned)
        cleaned = _PRICE.sub("", cleaned)
        cleaned = _NEAR.sub("", cleaned)
        cleaned = _QTY.sub("", cleaned)
        for hints in _CONDITION_HINTS.values():
            for h in hints:
                cleaned = re.sub(rf"\b{re.escape(h)}\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = _NOISE_WORDS.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
        return _DANGLING.sub("", cleaned).strip(" ,.-")

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
        for cls in ("economy", "compact", "midsize", "suv", "luxury", "minivan", "van", "truck", "convertible"):
            if re.search(rf"\b{cls}\b", text, re.IGNORECASE):
                q.vehicle_class = "van" if cls == "minivan" else cls
                break
        if q.vertical == Vertical.CAR_RENTAL:
            self._parse_vehicle(q, text)

    @staticmethod
    def _parse_vehicle(q: Query, text: str) -> None:
        """A known make/model ("rent a Toyota RAV4") becomes a model filter; infer its class when unstated."""
        dest = (q.destination.text if q.destination else "").lower()
        model = re.sub(r"\s+", " ", _CLASS_WORDS.sub("", q.item)).strip(" ,.-")
        squashed_model = re.sub(r"[^a-z0-9]", "", model.lower())
        make = _MAKES.search(model)
        known = make or any(m in squashed_model for models in _MODEL_CLASSES.values() for m in models.split())
        if model and known and model.lower() != dest:
            q.model = model
            q.brand = make.group(0).title() if make else None
        if q.vehicle_class is None:
            squashed = re.sub(r"[^a-z0-9]", "", text.lower())
            for cls, models in _MODEL_CLASSES.items():
                if any(m in squashed for m in models.split()):
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
    def _parse_times(text: str) -> tuple[time | None, time | None]:
        found: list[time] = []
        for m in _TIME_TOKEN.finditer(text):
            if m.group(3):
                hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower().replace(".", "")
                hour = hour % 12 + (12 if ampm == "pm" else 0)
            else:
                hour, minute = int(m.group(4)), int(m.group(5))
            if 0 <= hour < 24 and 0 <= minute < 60:
                found.append(time(hour, minute))
        if not found:
            return None, None
        return found[0], (found[1] if len(found) > 1 else found[0])

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
