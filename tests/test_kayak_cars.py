from datetime import date, time
from decimal import Decimal
from pathlib import Path

from pricefinder.config import Settings
from pricefinder.core.models import DateRange, Location, Query, Vertical
from pricefinder.providers.travel.kayak_cars import KayakCarsProvider, parse_results, results_url

FIXTURE = Path(__file__).parent / "fixtures" / "kayak_ewr.html"


def test_parse_results_from_live_capture():
    rows = parse_results(FIXTURE.read_text())
    assert len(rows) >= 8
    cheapest = min(rows, key=lambda r: min(p for _, p in r["sites"]))
    assert min(p for _, p in cheapest["sites"]) == Decimal("291")
    assert cheapest["pickup_location"] == "EWR: Newark"
    names = {n for r in rows for n, _ in r["sites"]}
    assert {"EconomyBookings", "Priceline"} <= names
    kia = next(r for r in rows if r["car"] == "Kia Rio")
    assert kia["vehicle_class"] == "Economy" and kia["passengers"] == "5" and kia["bags"] == "1" and kia["doors"] == "4"
    assert kia["score"] == 8.7 and kia["free_cancellation"] and kia["badge"] == "27% cheaper"


def test_results_url_uses_hour_granularity_and_known_slug():
    q = Query(
        raw="x",
        item="car",
        vertical=Vertical.CAR_RENTAL,
        destination=Location(text="EWR", iata="EWR"),
        dates=DateRange(start=date(2026, 11, 4), end=date(2026, 11, 10)),
        pickup_time=time(23, 30),
        dropoff_time=time(23, 30),
    )
    p = KayakCarsProvider()
    slug = p._known_slug("ewr", Settings())
    assert slug == "EWR-a8252"
    assert results_url(slug, q) == "https://www.kayak.com/cars/EWR-a8252/2026-11-04-23h/2026-11-10-23h?sort=price_a"
