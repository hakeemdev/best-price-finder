from datetime import date, time
from decimal import Decimal
from pathlib import Path

from pricefinder.config import Settings
from pricefinder.core.models import DateRange, Location, Query, Vertical
from pricefinder.core.query import RuleBasedQueryParser
from pricefinder.providers.travel.sixt import SixtDirectProvider, funnel_url, parse_offerlist

FIXTURE = Path(__file__).parent / "fixtures" / "sixt_ewr.txt"


def test_parse_offerlist_from_live_capture():
    rows = parse_offerlist(FIXTURE.read_text())
    assert len(rows) == 17
    cheapest = min(rows, key=lambda r: r["total"])
    assert cheapest["model"] == "Volkswagen Taos" and cheapest["total"] == Decimal("352.28")
    assert cheapest["per_day"] == Decimal("30.87") and cheapest["body"] == "suv"
    assert cheapest["seats"] == 5 and cheapest["bags"] == 2 and cheapest["transmission"] == "automatic"
    assert any(r["hot_offer"] for r in rows) and cheapest["unlimited_miles"]


def test_funnel_url_and_branch_lookup():
    q = Query(
        raw="x",
        item="SUV",
        vertical=Vertical.CAR_RENTAL,
        destination=Location(text="EWR", iata="EWR"),
        dates=DateRange(start=date(2026, 11, 4), end=date(2026, 11, 10)),
        pickup_time=time(23, 30),
        dropoff_time=time(23, 30),
    )
    p = SixtDirectProvider()
    assert p.branch_for(q, Settings()) == 45429
    url = funnel_url(45429, q)
    assert (
        "uci=45429" in url
        and "uda=20261104" in url
        and "rda=20261110" in url
        and "uti=2330" in url
        and "rti=2330" in url
    )


def test_parser_extracts_rental_times_and_airport():
    q = RuleBasedQueryParser().parse(
        "rent a car from EWR from 11:30PM 11/4/26 to 11:30PM 11/10/26", today=date(2026, 11, 2)
    )
    assert q.vertical == Vertical.CAR_RENTAL
    assert q.destination and q.destination.iata == "EWR"
    assert q.dates and q.dates.start == date(2026, 11, 4) and q.dates.end == date(2026, 11, 10)
    assert q.pickup_time == time(23, 30) and q.dropoff_time == time(23, 30)
    assert "11:30" not in q.item and "11/4" not in q.item
