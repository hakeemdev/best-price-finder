from datetime import date
from decimal import Decimal
from pathlib import Path

from pricefinder.core.models import DateRange, Location, Query, Travelers, Vertical
from pricefinder.providers.stays import airbnb, booking

FIXTURES = Path(__file__).parent / "fixtures"


def _query():
    return Query(
        raw="x",
        item="stay",
        vertical=Vertical.HOTEL,
        destination=Location(text="Dallas, TX"),
        dates=DateRange(start=date(2026, 11, 4), end=date(2026, 11, 10)),
        travelers=Travelers(adults=1),
    )


def test_airbnb_parse_live_capture():
    rows = airbnb.parse_results((FIXTURES / "airbnb_dallas.html").read_text())
    assert len(rows) >= 20
    sonesta = next(r for r in rows if r["title"].startswith("Sonesta Simply Suites"))
    assert sonesta["total"] == Decimal("476") and sonesta["nights"] == 6
    assert sonesta["rating"] == 4.15 and sonesta["reviews"] == 211
    assert sonesta["kind"] == "Hotel in Lake Highlands" and sonesta["featured_hotel"]
    assert sonesta["id"] == "1688504596625070397" and sonesta["airbnb_credit"] == Decimal("71")
    discounted = next(r for r in rows if r["original_total"])
    assert discounted["original_total"] > discounted["total"]
    assert all(r["total"] > 0 for r in rows)
    exact = [r for r in rows if r["nights"] == 6]
    assert len(exact) == 18  # Airbnb pads the page with 5- and 7-night alternatives; the provider drops those
    home = next(r for r in rows if r["kind"] == "Apartment in Dallas")
    assert home["title"] and not home["title"].startswith("Apartment in")


def test_airbnb_search_url():
    assert airbnb.place_slug("Dallas, TX") == "Dallas--TX"
    url = airbnb.search_url("Dallas, TX", _query())
    assert url == "https://www.airbnb.com/s/Dallas--TX/homes?checkin=2026-11-04&checkout=2026-11-10&adults=1"
    assert airbnb.search_url("Dallas, TX", _query(), price_max=60).endswith("&price_min=0&price_max=60")


def test_booking_parse_live_capture():
    rows = booking.parse_results((FIXTURES / "booking_dallas.html").read_text())
    assert len(rows) >= 15
    hostel = next(r for r in rows if r["name"] == "Bishop Hostel")
    assert hostel["total"] == Decimal("232") and hostel["nightly"] == Decimal("39")
    assert hostel["score"] == 7.5 and hostel["reviews"] == 92
    assert hostel["room"].startswith("Bed in 6-Bed Female Dormitory Room") and hostel["unit"] == "Bed in dorm"
    assert hostel["distance"] == "3.1 miles from downtown" and hostel["nights"] == 6 and hostel["adults"] == 1
    assert hostel["url"].startswith("https://www.booking.com/hotel/us/bishop-hostel.html")
    assert min(r["total"] for r in rows) == Decimal("60")  # sorted by price, cheapest first
    assert rows[0]["total"] <= rows[-1]["total"]


def test_booking_search_url():
    url = booking.search_url("Dallas, TX", _query())
    assert "ss=Dallas%2C+TX&checkin=2026-11-04&checkout=2026-11-10&group_adults=1&no_rooms=1" in url
    assert url.endswith("&group_children=0&order=price&selected_currency=USD")
