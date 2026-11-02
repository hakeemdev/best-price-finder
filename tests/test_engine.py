import pytest

from pricefinder.core.engine import SearchEngine
from pricefinder.core.models import Offer, ProviderKind, Query, Vertical
from pricefinder.core.registry import ProviderRegistry
from pricefinder.providers.base import Provider, ProviderContext


class ExplodingProvider(Provider):
    name = "boom"
    kind = ProviderKind.MOCK  # keep the mock provider in play alongside it
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
    assert result.offers and not result.providers_failed
    assert {o.offer.seller.type.value for o in result.offers} == {"direct", "ota"}


@pytest.mark.asyncio
async def test_travel_search_applies_rental_code_sweep(registry, repo):
    from pricefinder.core.models import AdjustmentKind, UserProfile

    repo.save_profile(UserProfile(id="renter", memberships=["usaa"], willing_to_sign_up=False))
    engine = SearchEngine(registry, repository=repo)
    result = await engine.search_text(
        "rental car SUV in Denver 2027-01-03 to 2027-01-10 profile", profile=repo.get_profile("renter")
    )
    assert result.query.vertical == Vertical.CAR_RENTAL
    assert result.query.dates and result.query.dates.nights == 7
    assert result.offers and not result.providers_failed
    direct = [o for o in result.offers if o.offer.seller.name in ("Hertz", "Avis")]
    assert direct, "mock should emit agency-direct rental offers"
    codes = [a for o in direct for a in o.adjustments if a.kind == AdjustmentKind.PROMO_CODE]
    assert codes and all("USAA" in a.description for a in codes)
    # Exactly one code per rental offer survives the stacking rules.
    assert all(sum(a.kind == AdjustmentKind.PROMO_CODE for a in o.adjustments) == 1 for o in direct)


def test_airport_pickup_filter_keeps_only_terminal_offers():
    from decimal import Decimal

    from pricefinder.core.models import Money, Seller, SellerType
    from pricefinder.core.normalize import on_airport

    def rental(note, oid):
        return Offer(
            id=oid,
            provider="t",
            vertical=Vertical.CAR_RENTAL,
            title="car",
            seller=Seller(name="x", type=SellerType.OTA),
            base_price=Money(amount=Decimal("300")),
            attributes={"pickup_note": note},
        )

    assert on_airport(rental("Airport terminal", "a"))
    assert on_airport(rental("Airport branch (Sixt counter)", "b"))
    assert not on_airport(rental("Call for pick-up", "c"))
    assert not on_airport(rental("Shuttle", "d"))
    assert not on_airport(rental(None, "e"))
    engine = SearchEngine(ProviderRegistry(), repository=None)
    q = Query(raw="x", item="car", vertical=Vertical.CAR_RENTAL, attributes={"airport_pickup": True})
    kept = engine._filter([rental("Airport terminal", "a"), rental("Shuttle", "d"), rental(None, "e")], q)
    assert [o.id for o in kept] == ["a"]
