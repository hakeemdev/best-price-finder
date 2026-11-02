"""Craigslist local listings (planned: RSS/HTML per metro area, radius filter, price extraction)."""

from __future__ import annotations

from ...core.models import ProviderKind, Vertical
from ..base import NotYetImplementedProvider


class CraigslistProvider(NotYetImplementedProvider):
    name = "craigslist"
    kind = ProviderKind.SCRAPE
    verticals = frozenset({Vertical.GOODS})
    description = "Craigslist local listings (planned)"
    planned_approach = "per-metro search pages with distance + price parsing"
