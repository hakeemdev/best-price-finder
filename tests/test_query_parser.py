from datetime import date
from decimal import Decimal

from pricefinder.core.models import Condition, Vertical
from pricefinder.core.query import RuleBasedQueryParser

TODAY = date(2026, 11, 2)
p = RuleBasedQueryParser()


def test_goods_with_price_and_location():
    q = p.parse("sony wh-1000xm5 under $300 near Austin, TX", today=TODAY)
    assert q.vertical == Vertical.GOODS
    assert q.max_price and q.max_price.amount == Decimal("300")
    assert q.location and "Austin" in q.location.text
    assert "sony wh-1000xm5" in q.item.lower()
    assert "under" not in q.item.lower()


def test_used_condition_detected():
    q = p.parse("used macbook pro m3", today=TODAY)
    assert Condition.USED in q.conditions
    assert q.item.lower() == "macbook pro m3"


def test_flight_route_and_dates():
    q = p.parse("flights SFO to JFK Dec 12 to Dec 19 for 2 adults business", today=TODAY)
    assert q.vertical == Vertical.FLIGHT
    assert q.origin and q.origin.iata == "SFO"
    assert q.destination and q.destination.iata == "JFK"
    assert q.dates and q.dates.start == date(2026, 12, 12) and q.dates.end == date(2026, 12, 19)
    assert q.travelers.adults == 2
    assert q.cabin == "business"


def test_hotel_with_relative_dates():
    q = p.parse("hotel in Chicago next weekend 2 rooms", today=TODAY)
    assert q.vertical == Vertical.HOTEL
    assert q.destination and q.destination.text.startswith("Chicago")
    assert q.dates and q.dates.start > TODAY and q.dates.nights == 2
    assert q.travelers.rooms == 2


def test_car_rental_class():
    q = p.parse("rental car SUV in Denver 2027-01-03 to 2027-01-10", today=TODAY)
    assert q.vertical == Vertical.CAR_RENTAL
    assert q.vehicle_class == "suv"
    assert q.dates and q.dates.nights == 7


def test_dates_in_the_past_roll_forward():
    q = p.parse("flights LAX to SEA Jan 5", today=TODAY)
    assert q.dates and q.dates.start == date(2027, 1, 5)


def test_airport_pickup_constraint_detected_and_stripped():
    q = p.parse("rent a car from EWR at the airport from 11:30PM 11/4/26 to 11:30PM 11/10/26", today=TODAY)
    assert q.vertical == Vertical.CAR_RENTAL
    assert q.attributes.get("airport_pickup") is True
    assert "airport" not in q.item.lower()
    assert q.destination and q.destination.iata == "EWR"
    plain = p.parse("rent a car from EWR 11/4/26 to 11/10/26", today=TODAY)
    assert "airport_pickup" not in plain.attributes
    assert plain.destination and plain.destination.iata == "EWR"  # dates right after the location must not hide it


def test_car_rental_model_request_sets_model_and_infers_class():
    q = p.parse("rent a Toyota RAV4 from EWR at the airport from 11:30PM 11/4/26 to 11:30PM 11/10/26", today=TODAY)
    assert q.vertical == Vertical.CAR_RENTAL
    assert q.model == "Toyota RAV4" and q.brand == "Toyota"
    assert q.vehicle_class == "suv"
    assert q.item == "Toyota RAV4"
    assert q.destination and q.destination.iata == "EWR"
    assert q.attributes.get("airport_pickup") is True
    assert q.dates and q.dates.start == date(2026, 11, 4) and q.dates.end == date(2026, 11, 10)
    loose = p.parse("rent a rav 4 from EWR 11/4/26 to 11/10/26", today=TODAY)
    assert loose.vertical == Vertical.CAR_RENTAL and loose.vehicle_class == "suv" and loose.model == "rav 4"
    generic = p.parse("rent a car from EWR 11/4/26 to 11/10/26", today=TODAY)
    assert generic.model is None and generic.vehicle_class is None
    cls_only = p.parse("rent an SUV from EWR 11/4/26 to 11/10/26", today=TODAY)
    assert cls_only.model is None and cls_only.vehicle_class == "suv"
    noise = p.parse("rental car in Denver 2027-01-03 to 2027-01-10 unlimited miles", today=TODAY)
    assert noise.model is None  # leftover words never become a model filter


def test_direct_only_constraint():
    for text in (
        "rent a car from DFW direct 11/4/26 to 11/10/26",
        "rent a car from DFW 11/4/26 to 11/10/26 booked directly with the rental agency",
        "rent a car from DFW 11/4/26 to 11/10/26 no third party sites",
        "rent a car from DFW 11/4/26 to 11/10/26 agency-direct only",
    ):
        q = p.parse(text, today=TODAY)
        assert q.attributes.get("direct_only") is True, text
        assert q.vertical == Vertical.CAR_RENTAL and q.destination and q.destination.iata == "DFW", text
        assert "direct" not in q.item.lower() and "third" not in q.item.lower(), text
    assert "direct_only" not in p.parse("rent a car from DFW 11/4/26 to 11/10/26", today=TODAY).attributes
