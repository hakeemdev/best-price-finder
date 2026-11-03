"""Enterprise Holdings brands booked direct, starting with National (headless browser; `pricefinder[browser]`).

National, Alamo and Enterprise share one booking platform. The home-page widget is driven like a person
would: type the airport, pick the dates, choose the times, "Check Availability", "Continue as Guest", and
read the car-select page. National is verified end to end; the Alamo and Enterprise widgets currently
answer automated sessions with a generic "something went wrong", so only National is registered.
"""

from __future__ import annotations

import logging
import re
from datetime import date, time
from decimal import Decimal
from urllib.parse import quote

from ...config import Settings, get_settings
from ...core.models import Money, Offer, ProviderKind, Query, Seller, SellerType, Vertical
from ...fetch.browser import browser_page, page_text, playwright_available, wait_for_prices
from ..base import Provider, ProviderContext

log = logging.getLogger(__name__)

_TOTAL = re.compile(r"^\$\s?(?P<amt>[\d,]+\.\d{2})\s+Est\.?\s+Total$", re.I)
_RATE = re.compile(r"^\$\s?(?P<amt>[\d,]+\.\d{2})\s*/\s*(?P<unit>day|week|month)$", re.I)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def parse_car_select(text: str) -> list[dict]:
    """Parse the car-select page text (one block per class ending in '$ X Est. Total')."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    rows: list[dict] = []
    for i, ln in enumerate(lines):
        m = _TOTAL.match(ln)
        if not m:
            continue
        lo = max(0, i - 16)
        block = lines[lo:i]
        try:
            fp = max(j for j, b in enumerate(block) if b.lower().startswith("features & pricing"))
        except ValueError:
            continue
        if fp < 2:
            continue
        model, vehicle_class = block[fp - 1], block[fp - 2]
        row = {
            "vehicle_class": vehicle_class,
            "car": re.sub(r"\s+or similar$", "", model, flags=re.I),
            "total": _dec(m.group("amt")),
            "rate": None,
            "rate_unit": None,
            "passengers": None,
            "bags": None,
        }
        tail = block[fp:]
        for j, b in enumerate(tail):
            if (r := _RATE.match(b)) and row["rate"] is None:
                row["rate"], row["rate_unit"] = _dec(r.group("amt")), r.group("unit").lower()
            elif b.lower() == "number of people" and j + 1 < len(tail) and tail[j + 1].isdigit():
                row["passengers"] = int(tail[j + 1])
            elif b.lower() == "luggage quantity" and j + 1 < len(tail) and tail[j + 1].isdigit():
                row["bags"] = int(tail[j + 1])
        rows.append(row)
    return rows


def time_label(t: time) -> str:
    """'11:30 PM' style label used by the time selects."""
    return f"{(t.hour % 12) or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def deeplink(host: str, location_id: str, query: Query, *, stop: str = "START") -> str:
    assert query.dates and query.dates.end
    pu = query.pickup_time or time(12, 0)
    do = query.dropoff_time or pu
    return (
        f"https://{host}/en/deeplink.html?v=2&pickUpLocation.searchCriteria={location_id}"
        f"&dropOffLocation.searchCriteria={location_id}"
        f"&pickUpDate={query.dates.start.isoformat()}&pickUpTime={pu.hour:02d}{pu.minute:02d}"
        f"&returnDate={query.dates.end.isoformat()}&returnTime={do.hour:02d}{do.minute:02d}"
        f"&oneway=false&prepay_selected=false&stop={stop}&age=25"
    )


def open_at(hours: list[dict] | None, when: date, at: time) -> bool | None:
    """True/False if the location's published hours cover `when` at `at`; None when unknown."""
    if not hours:
        return None
    for block in hours:
        for day in block.get("days") or []:
            if day.get("date") != when.isoformat():
                continue
            if day.get("closed_all_day"):
                return False
            if day.get("open_all_day"):
                return True
            hhmm = at.hour * 100 + at.minute
            for span in day.get("open_close_times") or []:
                try:
                    o, c = int(span.get("open_time", 0)), int(span.get("close_time", 2359))
                except (TypeError, ValueError):
                    continue
                if o <= hhmm <= c:
                    return True
            return False
    return None


class NationalProvider(Provider):
    name = "national"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.CAR_RENTAL})
    description = "National Car Rental, booked direct (headless browser)"
    typical_latency_s = 45.0

    home = "https://www.nationalcar.com/en/home.html"
    host = "www.nationalcar.com"
    seller_name = "National"
    sls = (
        "https://prd.location.enterprise.com/enterprise-sls/search/location/national/web/text/{q}"
        "?includeCountries=true&cor=US&locale=en_US&dto=true"
    )
    location_api = "https://prd-east.webapi.nationalcar.com/gma-national/location/{id}"
    loc_input = 'input.search-autocomplete__input, input[placeholder*="Airport Code" i]'
    pu_date = 'button[aria-label^="Pick Up Date"]'
    do_date = 'button[aria-label^="Return Date"]'
    pu_time = 'select[aria-label="Pick Up Time"]'
    do_time = 'select[aria-label="Return Time"]'
    submit = '[data-testid="check-availability-cta"]'

    def is_available(self, settings: Settings | None = None) -> bool:
        settings = settings or get_settings()
        return settings.browser_providers_enabled and playwright_available()

    def missing_settings(self, settings: Settings | None = None) -> list[str]:
        settings = settings or get_settings()
        out = []
        if not settings.browser_providers_enabled:
            out.append("browser_providers_enabled")
        if not playwright_available():
            out.append("playwright (pip install 'pricefinder[browser]' && playwright install chromium)")
        return out

    # -- browser steps ----------------------------------------------------------------

    async def _dismiss(self, page) -> None:
        await page.keyboard.press("Escape")
        for sel in ("#onetrust-accept-btn-handler", 'button:has-text("Accept All")', 'button[aria-label="Close"]'):
            try:
                b = page.locator(sel).first
                if await b.count() and await b.is_visible():
                    await b.click(timeout=1200)
                    await page.wait_for_timeout(400)
            except Exception:  # noqa: BLE001
                pass

    async def _location(self, page, where: str) -> None:
        inp = page.locator(self.loc_input).first
        await inp.click(timeout=8000)
        await inp.fill("")
        await inp.type(where, delay=90)
        await page.wait_for_timeout(3500)
        cand = page.locator("li, [role=option], button, div", has_text=re.compile(re.escape(where), re.I))
        for i in range(min(await cand.count(), 10)):
            el = cand.nth(i)
            try:
                if await el.is_visible():
                    t = (await el.inner_text()).strip()
                    if 0 < len(t) < 160 and re.search(rf"airport|\({re.escape(where)}\)", t, re.I):
                        await el.click(timeout=2000)
                        await page.wait_for_timeout(2000)
                        return
            except Exception:  # noqa: BLE001
                continue
        await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

    async def _pick_day(self, page, opener: str, when: date) -> None:
        label = f"{_MONTHS[when.month - 1]} {when.day}"
        cell = page.locator(f'button[aria-label="{label}"]').first
        if not (await cell.count() and await cell.is_visible()):
            await page.locator(opener).first.click(timeout=4000)
            await page.wait_for_timeout(1000)
        for _ in range(14):
            cell = page.locator(f'button[aria-label="{label}"]').first
            if await cell.count() and await cell.is_visible():
                await cell.click(timeout=4000)
                await page.wait_for_timeout(900)
                return
            nxt = page.locator('button[aria-label*="next" i], button:has-text("Next")').first
            if not await nxt.count():
                break
            await nxt.click(timeout=3000)
            await page.wait_for_timeout(600)
        raise RuntimeError(f"calendar day {label!r} not found")

    async def _pick_time(self, page, sel: str, wanted: time) -> str:
        s = page.locator(sel).first
        opts = await s.evaluate("s => Array.from(s.options).map(o => [o.value, o.text, o.disabled])")
        want = time_label(wanted)
        candidates = [want]
        # walk back in 30-minute steps when the exact slot is unavailable (counter closed)
        minutes = wanted.hour * 60 + wanted.minute
        for step in range(1, 5):
            m = minutes - 30 * step
            if m >= 0:
                candidates.append(time_label(time(m // 60, m % 60)))
        for c in candidates:
            for v, t, dis in opts:
                if t.strip().startswith(c) and not dis:
                    await s.select_option(value=v)
                    return t.strip()
        raise RuntimeError(f"no selectable time near {want}")

    async def _lookup(self, page, where: str) -> tuple[str | None, dict | None]:
        """Location id (for the deep link) and the branch record (hours, wayfinding) via the site's own APIs."""
        try:
            raw = await page.evaluate(
                "(u) => fetch(u, {credentials: 'include'}).then(r => r.json()).catch(() => null)",
                self.sls.format(q=quote(where)),
            )
            airports = (raw or {}).get("airports") or []
            loc_id = str(airports[0]["id"]) if airports else None
            if not loc_id:
                return None, None
            rec = await page.evaluate(
                "(u) => fetch(u, {credentials: 'include'}).then(r => r.json()).catch(() => null)",
                self.location_api.format(id=loc_id),
            )
            return loc_id, (rec or {}).get("location") or rec
        except Exception as exc:  # noqa: BLE001
            log.info("%s: location lookup failed: %s", self.name, exc)
            return None, None

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        if not (query.dates and query.dates.end):
            log.info("%s: need pickup and drop-off dates", self.name)
            return []
        loc = query.destination or query.location or query.origin
        where = (loc.iata or loc.text or "") if loc else ""
        if not where:
            return []
        pu_t = query.pickup_time or time(12, 0)
        do_t = query.dropoff_time or pu_t
        async with browser_page(timezone="America/Chicago", headless=ctx.settings.browser_headless) as page:
            await page.goto(self.home, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(6000)
            await self._dismiss(page)
            loc_id, record = await self._lookup(page, where)
            await self._location(page, where)
            await self._pick_day(page, self.pu_date, query.dates.start)
            await self._pick_day(page, self.do_date, query.dates.end)
            pu_label = await self._pick_time(page, self.pu_time, pu_t)
            do_label = await self._pick_time(page, self.do_time, do_t)
            await page.locator(self.submit).first.click(timeout=6000)
            for _ in range(4):
                await page.wait_for_timeout(2500)
                guest = page.locator("button, a", has_text=re.compile(r"continue as guest", re.I)).first
                if await guest.count() and await guest.is_visible():
                    await guest.click(timeout=4000)
                    break
            text = await wait_for_prices(page, min_prices=8, timeout_s=max(ctx.timeout - 25, 20), settle_s=4.0)
            text = text or await page_text(page)
        rows = parse_car_select(text)
        if not rows:
            log.info("%s: no priced vehicles on the results page (site may have refused the session)", self.name)
            return []
        days = max(query.dates.nights or 1, 1)
        url = deeplink(self.host, loc_id, query) if loc_id else self.home
        wayfinding = " ".join(w.get("text", "") for w in (record or {}).get("wayfindings") or []).lower()
        if "shuttle" in wayfinding:
            pickup_note = f"Airport location via rental-car shuttle ({self.seller_name} counter)"
        else:
            pickup_note = f"Airport branch ({self.seller_name} counter)"
        open_pu = open_at((record or {}).get("hours"), query.dates.start, pu_t)
        offers: list[Offer] = []
        for r in rows:
            offers.append(
                Offer(
                    id=self.make_offer_id(self.name, query.cache_key(), re.sub(r"\W+", "-", r["car"].lower())),
                    provider=self.name,
                    vertical=Vertical.CAR_RENTAL,
                    title=f"{self.seller_name} {r['vehicle_class']}: {r['car']} or similar, {days} days",
                    url=url,
                    seller=Seller(name=self.seller_name, type=SellerType.DIRECT, merchant_id=self.name),
                    base_price=Money(amount=r["total"], currency=query.currency),
                    in_stock=True,
                    location=loc,
                    attributes={
                        "car": r["car"],
                        "vehicle_class": r["vehicle_class"],
                        "passengers": r["passengers"],
                        "bags": r["bags"],
                        "rate": f"${r['rate']} / {r['rate_unit']}" if r["rate"] else None,
                        "per_day": (r["total"] / days).quantize(Decimal("0.01")),
                        "days": days,
                        "pickup_note": pickup_note,
                        "pickup_time_booked": pu_label,
                        "dropoff_time_booked": do_label,
                        "times_adjusted": pu_label != time_label(pu_t) or do_label != time_label(do_t),
                        "open_at_pickup": open_pu,
                        "total_includes_taxes_fees": True,
                    },
                )
            )
        return offers
