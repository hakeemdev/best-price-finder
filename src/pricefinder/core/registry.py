"""Provider registry with entry-point discovery.

Third-party packages can ship providers by declaring an entry point in the
`pricefinder.providers` group; they'll be discovered automatically.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from ..providers.base import Provider
from .models import Vertical

log = logging.getLogger(__name__)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.name in self._providers:
            log.warning("provider %s already registered; replacing", provider.name)
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def get(self, name: str) -> Provider:
        return self._providers[name]

    def all(self) -> list[Provider]:
        return list(self._providers.values())

    def for_vertical(self, vertical: Vertical, *, only_available: bool = True) -> list[Provider]:
        return [
            p for p in self._providers.values() if vertical in p.verticals and (not only_available or p.is_available())
        ]

    def discover(self, group: str = "pricefinder.providers") -> int:
        """Load every provider advertised through package entry points. Returns count loaded."""
        loaded = 0
        for ep in entry_points(group=group):
            try:
                cls = ep.load()
                self.register(cls())
                loaded += 1
            except Exception as exc:  # noqa: BLE001 - a broken plugin must not kill the app
                log.warning("failed to load provider %s: %s", ep.name, exc)
        return loaded


_default: ProviderRegistry | None = None


def default_registry() -> ProviderRegistry:
    global _default
    if _default is None:
        _default = ProviderRegistry()
        _default.discover()
    return _default
