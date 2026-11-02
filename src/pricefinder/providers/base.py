"""Provider contract. Every price source implements this.

A provider:
- declares which verticals it serves and what credentials/tools it needs,
- turns a `Query` into zero or more `Offer`s,
- never ranks or applies savings (the engine does that),
- must be safe to call concurrently and must respect `ctx.timeout`.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field

from ..config import Settings, get_settings
from ..core.models import Offer, ProviderKind, Query, Vertical
from ..fetch.http import HttpClient

log = logging.getLogger(__name__)


@dataclass
class ProviderContext:
    settings: Settings = field(default_factory=get_settings)
    http: HttpClient | None = None
    timeout: float = 30.0

    def client(self) -> HttpClient:
        if self.http is None:
            self.http = HttpClient(settings=self.settings)
        return self.http


class Provider(abc.ABC):
    name: str = "base"
    kind: ProviderKind = ProviderKind.API
    verticals: frozenset[Vertical] = frozenset()
    description: str = ""
    #: setting names on `Settings` that must be non-empty for this provider to run
    required_settings: tuple[str, ...] = ()
    #: whether the user must opt in (e.g. scraping sources with restrictive terms)
    opt_in: bool = False
    #: rough cost in seconds; used to budget timeouts
    typical_latency_s: float = 3.0

    def is_available(self, settings: Settings | None = None) -> bool:
        settings = settings or get_settings()
        return all(getattr(settings, key, None) for key in self.required_settings)

    def missing_settings(self, settings: Settings | None = None) -> list[str]:
        settings = settings or get_settings()
        return [k for k in self.required_settings if not getattr(settings, k, None)]

    @abc.abstractmethod
    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]: ...

    def make_offer_id(self, *parts: str) -> str:
        return f"{self.name}:" + ":".join(p for p in parts if p)

    def __repr__(self) -> str:
        return f"<Provider {self.name} kind={self.kind} verticals={sorted(self.verticals)}>"


class NotYetImplementedProvider(Provider):
    """Placeholder for sources on the roadmap. Shows up in `pf providers` but returns nothing."""

    planned_approach: str = ""

    def is_available(self, settings: Settings | None = None) -> bool:
        return False

    async def search(self, query: Query, ctx: ProviderContext) -> list[Offer]:
        log.info("provider %s is not implemented yet (%s)", self.name, self.planned_approach)
        return []
