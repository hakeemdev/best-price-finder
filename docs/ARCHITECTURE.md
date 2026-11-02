# Architecture

## Core ideas

1. **One query shape, one offer shape.** `Query` is rich enough to describe a pair of headphones, a round-trip flight, a hotel stay or a car rental. `Offer` is what every provider returns, regardless of vertical. Vertical-specific detail lives in `Offer.attributes`.
2. **Providers only fetch.** They never rank, never apply coupons, never decide what is "best". That keeps adapters small and testable and keeps the ranking policy in one place.
3. **Savings are first-class data.** Every discount, reward or fee is an `Adjustment` with a kind, amount, confidence, and the action the user has to take. The result is auditable: you can see exactly why an offer ranked where it did.
4. **Append-only history.** Every observed offer is recorded. "Best price ever" and trend lines fall out of the data for free, and future indexing / archival features build on the same tables.
5. **Degrade gracefully.** Missing keys skip a provider. A crashing or slow provider is isolated with its own timeout and reported in `SearchResult.providers_failed`.

## Pipeline

| Stage | Module | Notes |
|---|---|---|
| Parse | `core/query.py`, `core/llm_parser.py` | Rule-based always runs; with an Anthropic key the LLM parser refines it via structured output and falls back to the rules result on any failure. `PF_QUERY_PARSER` = auto / rules / llm. |
| Select providers | `core/registry.py` | By vertical, availability, opt-in flag, and `include_local` / `include_online`. Entry-point discovery lets external packages add providers. |
| Fan out | `core/engine.py` | `asyncio.gather` under a semaphore; per-provider `wait_for` timeout. |
| Normalize | `core/normalize.py` | URL / identifier dedupe, `product_key` for cross-seller history, fuzzy relevance filter. |
| Savings | `savings/*` | Each `SavingsSource.evaluate(offer, query, profile)` returns adjustments: coupons, signup offers, rental-code sweep, memberships, cashback portals, card rewards. Stack rules (one card, one portal, one promo unless stackable) applied in the ranker. |
| Rank | `core/ranking.py` | Expected effective price + dollar-equivalent penalties (distance, seller risk, stock uncertainty). Also yields a guaranteed price. |
| Persist | `storage/` | SQLAlchemy; SQLite by default, Postgres via `pricefinder[postgres]`. |

## Key models

- `Money` is `Decimal` + currency and refuses cross-currency arithmetic. FX conversion is a planned normalization step.
- `Offer.sticker_total` = base + shipping + taxes + fees.
- `PricedOffer.effective_total` = sticker minus `sum(savings * confidence)`; `guaranteed_total` counts only confidence-1.0 adjustments.
- `UserProfile` holds cards, loyalty programs, memberships, home location and two consent flags: `willing_to_sign_up` (newsletters, store accounts) and `willing_to_open_cards` (credit card signup bonuses).

## Provider kinds

| kind | meaning | examples |
|---|---|---|
| api | official keyed API | eBay Browse, Best Buy, Walmart affiliate, SerpApi |
| scrape | HTML / RSS parsing | Craigslist |
| browser | headless Chromium via Playwright (`fetch/browser.py`); parsers are pure functions tested on saved captures | Kayak cars, Sixt direct; Facebook Marketplace (planned, user session) |
| local | nearby in-store stock & price | retailer store-availability endpoints |
| mock | deterministic test data | `mock` |

## Extension points

- New source: subclass `providers.base.Provider`, register an entry point. See `docs/PROVIDERS.md`.
- New savings type: subclass `savings.base.SavingsSource`, add to `SearchEngine(savings=[...])`.
- New parser: implement `QueryParser` protocol.
- Different ranking policy: pass `Ranker(RankingWeights(...))`.
- Storage: any SQLAlchemy URL.
