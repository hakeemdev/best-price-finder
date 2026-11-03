from datetime import date, time
from decimal import Decimal
from pathlib import Path

from pricefinder.core.models import DateRange, Location, Query, Vertical
from pricefinder.providers.travel.ehi import deeplink, open_at, parse_car_select, time_label

FIXTURE = Path(__file__).parent / "fixtures" / "national_dfw.txt"


def test_parse_car_select_from_live_capture():
    rows = parse_car_select(FIXTURE.read_text())
    assert len(rows) == 26
    cheapest = min(rows, key=lambda r: r["total"])
    assert cheapest["total"] == Decimal("638.91")
    assert cheapest["vehicle_class"] == "Standard Elite SUV" and cheapest["car"] == "Audi Q3, Cadillac XT4"
    assert cheapest["rate"] == Decimal("448.99") and cheapest["rate_unit"] == "week"
    economy = next(r for r in rows if r["vehicle_class"] == "Economy")
    assert economy["car"] == "Mitsubishi Mirage" and economy["total"] == Decimal("655.76")
    assert economy["passengers"] == 4 and economy["bags"] == 2
    assert all(r["total"] > 0 and r["car"] for r in rows)


def test_time_label_and_deeplink():
    assert time_label(time(23, 30)) == "11:30 PM"
    assert time_label(time(0, 0)) == "12:00 AM"
    assert time_label(time(9, 5)) == "9:05 AM"
    q = Query(
        raw="x",
        item="car",
        vertical=Vertical.CAR_RENTAL,
        destination=Location(text="DFW", iata="DFW"),
        dates=DateRange(start=date(2026, 11, 4), end=date(2026, 11, 10)),
        pickup_time=time(23, 30),
        dropoff_time=time(23, 30),
    )
    url = deeplink("www.nationalcar.com", "1018958", q)
    assert url.startswith("https://www.nationalcar.com/en/deeplink.html?v=2&pickUpLocation.searchCriteria=1018958")
    assert "pickUpDate=2026-11-04&pickUpTime=2330&returnDate=2026-11-10&returnTime=2330" in url


def test_open_at_reads_published_hours():
    hours = [
        {
            "days": [
                {"date": "2026-11-04", "open_all_day": True, "closed_all_day": False, "open_close_times": []},
                {
                    "date": "2026-11-05",
                    "open_all_day": False,
                    "closed_all_day": False,
                    "open_close_times": [{"open_time": "600", "close_time": "2300"}],
                },
            ]
        }
    ]
    assert open_at(hours, date(2026, 11, 4), time(23, 30)) is True
    assert open_at(hours, date(2026, 11, 5), time(23, 30)) is False
    assert open_at(hours, date(2026, 11, 5), time(10, 0)) is True
    assert open_at(hours, date(2026, 11, 6), time(10, 0)) is None
    assert open_at(None, date(2026, 11, 6), time(10, 0)) is None
