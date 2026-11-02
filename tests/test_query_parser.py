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
