# Roadmap

## Phase 0: foundation (this repo today)
- [x] Domain models for goods, flights, hotels, car rentals, reservations
- [x] Rule-based query parser (vertical, dates, route, location, budget, condition, travelers)
- [x] Provider registry with entry-point plugins; async fan-out with isolation and timeouts
- [x] Savings layer: coupons, promo codes, credit-card rewards (best card + signup bonuses), quick signup offers, cashback portals
- [x] Ranker with expected vs guaranteed price and dollar-equivalent penalties
- [x] Price history (append-only), best-ever, profiles; SQLite default, Postgres optional
- [x] CLI (`pf`) and HTTP API
- [x] Providers: mock, eBay Browse API, Google Shopping / Flights / Hotels via SerpApi
- [x] Best Buy official API with in-store stock + distance; Walmart affiliate API (signed requests)
- [x] LLM-backed query parser (Anthropic SDK, structured output, rule-based fallback)
- [x] Car-rental discount-code sweep (AAA / Costco / USAA / AARP / loyalty) and membership benefits
- [x] Live car rentals: Kayak results (agencies + OTAs, hour-granular times) and Sixt direct via headless browser; pickup/drop-off times in the query model

## Phase 1: coverage
- [ ] Direct retailer adapters: Amazon (PA-API / affiliate), Target, Newegg, B&H, Micro Center, Costco
- [ ] Local: Target / Walmart store stock, Costco warehouse pricing, Google local results, grocery feeds
- [ ] Marketplaces: Facebook Marketplace (opt-in, own browser session), Craigslist, OfferUp, Mercari, Swappa, Back Market
- [ ] Car rentals: more agency-direct funnels (Hertz/Avis/Budget/Enterprise), Turo, Costco Travel; Kayak location auto-resolution for cities; Priceline/Expedia/Skyscanner are bot-walled headless (needs user-owned browser session)
- [ ] Flights: airline direct, Skyscanner/Kayak, Southwest; points redemption valuation
- [ ] Hotels: Airbnb/Vrbo, Booking, Hotels.com One Key, resort-fee parsing, points redemption valuation
- [ ] Reservations: Resy/OpenTable availability, Ticketmaster/StubHub/SeatGeek resale, Viator/GetYourGuide

## Phase 2: savings intelligence
- [ ] Live coupon feeds and community code aggregation with success-rate tracking
- [ ] Checkout code testing via browser automation (opt-in)
- [ ] Automated card catalog refresh; per-user point valuations; category-quarter bonuses
- [ ] Loyalty status perks (free upgrades, waived fees); auto-refresh membership + rental-code catalogs
- [ ] Price-match policy engine (retailer matches competitor X within Y days)
- [ ] Tax estimation by destination / pickup location
- [ ] Currency conversion for cross-border offers

## Phase 3: data & memory
- [ ] Product index: UPC / ASIN / model-number resolution so "xm5" and "WH-1000XM5" collapse to one product
- [ ] Price history charts, "wait or buy" recommendations, alerts when price drops below best-ever
- [ ] Scheduled re-checks for saved searches; fare / rate watch for travel
- [ ] Archive crawl results for offline querying

## Phase 4: understanding & UX
- [ ] Multi-item lists and conversational refinement on top of the LLM parser
- [ ] Web UI
- [ ] Browser extension that overlays effective price on retailer pages
- [ ] Multi-currency, multi-country marketplaces
