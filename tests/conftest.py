from __future__ import annotations

import pytest

from pricefinder.core.models import CardHolding, UserProfile
from pricefinder.core.registry import ProviderRegistry
from pricefinder.providers.goods.mock import MockGoodsProvider
from pricefinder.storage.repository import Repository


@pytest.fixture
def registry() -> ProviderRegistry:
    r = ProviderRegistry()
    r.register(MockGoodsProvider())
    return r


@pytest.fixture
def repo() -> Repository:
    return Repository("sqlite:///:memory:")


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        id="test",
        cards=[CardHolding(card_id="citi_double_cash"), CardHolding(card_id="chase_sapphire_preferred")],
        willing_to_sign_up=True,
        willing_to_open_cards=False,
    )
