"""Search orchestration: parse -> fan out to providers -> normalize -> apply savings -> rank -> store."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ..config import Settings, get_settings
from ..providers.base import Provider, ProviderContext
from ..savings import SavingsSource, default_sources
from ..storage.repository import Repository
from .llm_parser import build_parser
from .models import Offer, PricedOffer, ProviderKind, Query, SearchResult, UserProfile
from .normalize import dedupe, matches_query, matches_vehicle, on_airport, product_key
from .query import QueryParser
from .ranking import Ranker
from .registry import ProviderRegistry, default_registry

log = logging.getLogger(__name__)


class SearchEngine:
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        *,
        parser: QueryParser | None = None,
        ranker: Ranker | None = None,
        savings: list[SavingsSource] | None = None,
        repository: Repository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or default_registry()
        self.parser = parser or build_parser(self.settings)
        self.ranker = ranker or Ranker()
        self.savings = savings if savings is not None else default_sources()
        self.repo = repository

    # -- entry points ---------------------------------------------------------

    async def search_text(
        self, text: str, *, profile: UserProfile | None = None, providers: list[str] | None = None
    ) -> SearchResult:
        return await self.search(self.parser.parse(text), profile=profile, providers=providers)

    async def search(
        self, query: Query, *, profile: UserProfile | None = None, providers: list[str] | None = None
    ) -> SearchResult:
        started = datetime.now(UTC)
        profile = profile or self._load_profile(query.profile_id)
        selected = self._select_providers(query, providers)
        ctx = ProviderContext(settings=self.settings, timeout=self.settings.provider_timeout_seconds)

        raw_offers, failures = await self._fan_out(selected, query, ctx)
        offers = self._filter(dedupe(raw_offers), query)
        priced = [self._price(o, query, profile) for o in offers]
        ranked = self.ranker.rank(priced, query)

        best_ever = None
        if self.repo is not None:
            try:
                self.repo.record_search(query, ranked, [p.name for p in selected])
                best_ever = self.repo.best_ever(product_key(ranked[0].offer)) if ranked else None
            except Exception as exc:  # noqa: BLE001
                log.warning("failed to persist search: %s", exc)

        if ctx.http is not None:
            await ctx.http.aclose()

        return SearchResult(
            query=query,
            offers=ranked,
            providers_queried=[p.name for p in selected],
            providers_failed=failures,
            started_at=started,
            finished_at=datetime.now(UTC),
            best_ever=best_ever,
        )

    # -- stages ---------------------------------------------------------------

    def _select_providers(self, query: Query, names: list[str] | None) -> list[Provider]:
        if names:
            return [self.registry.get(n) for n in names]
        candidates = self.registry.for_vertical(query.vertical)
        out: list[Provider] = []
        for p in candidates:
            if p.opt_in:
                continue
            if p.kind.value == "local" and not query.include_local:
                continue
            if p.kind.value != "local" and not query.include_online:
                continue
            out.append(p)
        # The mock provider is for demos and tests: drop it as soon as a real source is available.
        if any(p.kind != ProviderKind.MOCK for p in out):
            out = [p for p in out if p.kind != ProviderKind.MOCK]
        return out

    async def _fan_out(
        self, providers: list[Provider], query: Query, ctx: ProviderContext
    ) -> tuple[list[Offer], dict[str, str]]:
        sem = asyncio.Semaphore(self.settings.max_concurrent_providers)
        failures: dict[str, str] = {}

        async def run(p: Provider) -> list[Offer]:
            async with sem:
                try:
                    return await asyncio.wait_for(p.search(query, ctx), timeout=ctx.timeout)
                except TimeoutError:
                    failures[p.name] = f"timed out after {ctx.timeout}s"
                except Exception as exc:  # noqa: BLE001 - one bad provider must not sink the search
                    failures[p.name] = f"{type(exc).__name__}: {exc}"
                    log.exception("provider %s failed", p.name)
                return []

        results = await asyncio.gather(*(run(p) for p in providers))
        return [o for batch in results for o in batch], failures

    def _filter(self, offers: list[Offer], query: Query) -> list[Offer]:
        out: list[Offer] = []
        for o in offers:
            if query.conditions and o.condition not in query.conditions and o.condition.value != "unknown":
                continue
            if not query.include_used and o.condition.value in ("used", "refurbished"):
                continue
            if query.max_drive_km and o.distance_km and o.distance_km > query.max_drive_km:
                continue
            if query.vertical.value == "goods" and not matches_query(o.title, query.item):
                continue
            if query.attributes.get("airport_pickup") and o.vertical.value == "car_rental" and not on_airport(o):
                continue
            if o.vertical.value == "car_rental" and not matches_vehicle(o, query):
                continue
            out.append(o)
        return out

    def _price(self, offer: Offer, query: Query, profile: UserProfile) -> PricedOffer:
        adjustments = []
        for src in self.savings:
            try:
                adjustments.extend(src.evaluate(offer, query, profile))
            except Exception as exc:  # noqa: BLE001
                log.warning("savings source %s failed on %s: %s", src.name, offer.id, exc)
        return self.ranker.price(offer, adjustments)

    def _load_profile(self, profile_id: str | None) -> UserProfile:
        if self.repo is not None:
            stored = self.repo.get_profile(profile_id or "default")
            if stored is not None:
                return stored
        return UserProfile(id=profile_id or "default")
