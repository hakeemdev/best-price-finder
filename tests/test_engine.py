import pytest

from pricefinder.core.engine import SearchEngine
from pricefinder.core.models import Offer, Query, Vertical
from pricefinder.providers.base import Provider, ProviderContext


class ExplodingProvider(Provider):
    name = "boom"
    verticals = frozenset({Vertical.GOODS})

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        raise RuntimeError("upstream down")


@pytest.mark.asyncio
async def test_end_to_end_with_mock_provider(registry, repo, profile):
    repo.save_profile(profile)
    engine = SearchEngine(registry, repository=repo)
    q = Query(raw="sony wh-1000xm5", item="sony wh-1000xm5", profile_id="test")
    result = await engine.search(q)
    assert result.providers_queried == ["mock"]
    assert result.offers
    best = result.offers[0]
    assert best.effective_total.amount <= best.sticker_total.amount
    assert any(a.kind.value == "credit_card_reward" for a in best.adjustments)
    # Ranked ascending by score
    scores = [o.score for o in result.offers]
    assert scores == sorted(scores)
    # History recorded
    assert repo.history("sony")
    assert result.best_ever is not None


@pytest.mark.asyncio
async def test_failing_provider_does_not_break_search(registry, repo):
    registry.register(ExplodingProvider())
    engine = SearchEngine(registry, repository=repo)
    result = await engine.search(Query(raw="x", item="widget"))
    assert "boom" in result.providers_failed
    assert "upstream down" in result.providers_failed["boom"]
    assert result.offers


@pytest.mark.asyncio
async def test_search_text_routes_flights_to_flight_providers(registry):
    engine = SearchEngine(registry, repository=None)
    result = await engine.search_text("flights SFO to JFK Dec 12 to Dec 19")
    assert result.query.vertical == Vertical.FLIGHT
    assert result.providers_queried == ["mock"]
