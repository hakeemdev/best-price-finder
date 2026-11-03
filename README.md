# best-price-finder

Hunt down the absolute best **effective** price for anything: consumer goods, electronics, flights, hotels, rental cars, reservations, services. Searches the whole internet *and* the shops near you, then layers on coupons, promo codes, credit-card rewards, quick signup offers, cashback portals and loyalty perks so the number you see is what you actually pay.

```
$ pf search "sony wh-1000xm5 under $300 near Austin, TX"
goods: sony wh-1000xm5   providers: google_shopping, ebay, mock, local_inventory

 #   effective   sticker  seller        cond   title                                   savings applied
 1      248.10    279.99  Best Buy      new    Sony WH-1000XM5 (open box)              -14.00 Pay with Citi Double Cash: 2% back; -17.89 ...
 2      251.44    269.00  eBay seller   used   Sony WH1000XM5 Wireless Headphones      ...
best effective price ever recorded for this item: 231.00 USD
```

Status: **pre-alpha foundation**. The engine, ranking, savings model, storage, CLI and API are in place; provider coverage is growing. See [docs/ROADMAP.md](docs/ROADMAP.md).

## What "best price" means here

```
effective price = base price
                + shipping + taxes + fees            (sticker total)
                - coupons / promo codes
                - credit card rewards (best card you hold, or one worth opening)
                - quick signup offers (newsletter, store account, app)
                - cashback portals (Rakuten, TopCashback, ...)
                - membership benefits (Costco, AAA, AARP, Prime, student, military)
                - rental discount-code sweep (one best CDP/AWD/BCD code per rental)
```

Every adjustment carries a **confidence**. The ranker reports both the *expected* effective price and a *guaranteed* price that only counts certain savings, and applies soft penalties for distance, individual sellers, low ratings and unknown stock so a sketchy listing 60 km away doesn't beat a reputable retailer by two dollars.

## Verticals

| Vertical | Examples | Sources (now / planned) |
|---|---|---|
| goods | electronics, appliances, groceries, anything with a SKU | Google Shopping (Amazon, Walmart, Best Buy, Target, ...), eBay, Best Buy direct + in-store stock, Walmart direct + marketplace / Target, Costco, Facebook Marketplace, Craigslist, OfferUp |
| flight | one-way, round-trip, multi-city | Google Flights / airline direct, points redemptions, error fares |
| hotel | hotels, resorts, vacation rentals | Google Hotels (direct + OTA) / Airbnb, Vrbo, points redemptions, resort-fee aware |
| car_rental | agencies, peer-to-peer | **live:** Kayak (every major agency + OTAs), Sixt direct; discount-code sweep (AAA, Costco, USAA, AARP, loyalty) / planned: more agency-direct funnels, Turo, Costco Travel |
| reservation | restaurants, events, tickets, experiences | planned |
| service | subscriptions, insurance, plans | planned |

## Install

```bash
git clone https://github.com/hakeemdev/best-price-finder
cd best-price-finder
uv sync --dev            # or: pip install -e ".[dev]"
cp .env.example .env     # add any API keys you have; everything is optional
uv run pf providers      # see what's ready
uv run pf search "nintendo switch oled" --provider mock   # works offline
```

Keys you may want (free tiers exist for all of them):

- `PF_SERPAPI_KEY` turns on Google Shopping, Google Flights and Google Hotels.
- `PF_EBAY_CLIENT_ID` / `PF_EBAY_CLIENT_SECRET` turns on eBay (official Browse API).
- `PF_BESTBUY_API_KEY` turns on Best Buy, including in-store stock near `PF_HOME_POSTAL_CODE`.
- `PF_WALMART_CONSUMER_ID` / `PF_WALMART_PRIVATE_KEY_PATH` turns on Walmart (needs `pricefinder[walmart]`).
- Car rentals need no key: `pip install -e ".[browser]" && playwright install chromium` enables the Kayak and Sixt headless-browser adapters. Set `PF_BROWSER_PROVIDERS_ENABLED=false` to turn them off.
- `PF_ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY`) turns on the LLM query parser (needs `pricefinder[llm]`); messy requests like "a 65 inch oled I can grab today under 1500" get understood instead of keyword-matched. Set `PF_QUERY_PARSER=rules` to force the offline parser.

## Usage

```bash
pf search "flights SFO to JFK Dec 12 to Dec 19 for 2 adults"
pf search "hotel in Chicago next weekend 2 rooms"
pf search "hotel or airbnb in Dallas, TX from 11/4/26 to 11/10/26 for 1 adult"   # live Airbnb + Booking.com
pf search "rent a car from EWR from 11:30PM 11/4/26 to 11:30PM 11/10/26"   # live Kayak + Sixt
pf search "rent a Toyota RAV4 from EWR at the airport from 11:30PM 11/4/26 to 11:30PM 11/10/26"
pf search "rent a car from DFW direct from 11:30PM 11/4/26 to 11:30PM 11/10/26"   # agency-direct only (Sixt, National, Kayak direct listings)
#   "at the airport" keeps only in-terminal pick-up; a make/model or class (SUV, van, luxury) filters the cars
pf search "used macbook pro m3 under $1200" --json
pf parse "..."                       # see how a query is interpreted
pf history "wh-1000xm5"              # prices seen in past searches
pf profile add-card chase_sapphire_preferred
pf profile set willing_to_open_cards true
pf profile set memberships costco,aaa,prime     # unlocks rental codes + member rates
pf serve                             # HTTP API at http://127.0.0.1:8000/docs
```

## Architecture

```
free text -> QueryParser -> Query
                               |
            ProviderRegistry.for_vertical(query.vertical)
                               |
   asyncio fan-out (timeouts, per-host rate limits, isolated failures)
                               |
          Offer[] -> dedupe + relevance filter
                               |
  SavingsSources (coupons, rewards, signup, cashback, loyalty) -> Adjustment[]
                               |
         Ranker -> PricedOffer[] (effective, guaranteed, score, reasons)
                               |
            Repository (SQLite / Postgres): price history, best-ever
```

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Adding a source is one class; see [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Project layout

```
src/pricefinder/
  core/        models, query parsing, registry, engine, ranking, normalization
  providers/   goods/ travel/ local/ -- one adapter per source
  savings/     coupons, credit-card rewards, signup offers, cashback, memberships, rental codes
  storage/     SQLAlchemy models + repository (price history, profiles)
  fetch/       shared HTTP client (retries, rate limits, cache)
  api/         FastAPI app
  cli.py       `pf` command
data/          cards, coupons, cashback, memberships, rental_codes seed catalogs
tests/
```

## Responsible use

Prefer official APIs. Browser adapters (Kayak, Sixt) load one results page per search on your own machine, the same request a shopper makes; they can be disabled with `PF_BROWSER_PROVIDERS_ENABLED=false`. Sources whose terms forbid automated access (e.g. Facebook Marketplace) are **opt-in** and designed to run through your own logged-in browser session. Rate limits are enforced per host. Card and coupon data in `data/` are approximations; always verify terms before relying on them.

## License

MIT
