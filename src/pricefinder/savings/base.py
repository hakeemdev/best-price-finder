from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

import yaml

from ..core.models import Adjustment, Offer, Query, UserProfile


class SavingsSource(abc.ABC):
    name: str = "savings"

    @abc.abstractmethod
    def evaluate(self, offer: Offer, query: Query, profile: UserProfile) -> list[Adjustment]: ...


def load_yaml(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open() as fh:
        return yaml.safe_load(fh) or {}


def merchant_key(offer: Offer) -> str:
    """Normalize a seller into a key usable across coupon / cashback / rewards catalogs."""
    if offer.seller.merchant_id:
        return offer.seller.merchant_id.lower()
    return "".join(ch for ch in offer.seller.name.lower() if ch.isalnum())
