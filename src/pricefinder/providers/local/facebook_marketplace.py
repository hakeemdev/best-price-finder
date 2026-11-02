"""Facebook Marketplace. There is no public API and automated access is against Meta's terms,
so this adapter is opt-in and intended to run through the user's own logged-in browser session
(Playwright, `pricefinder[browser]`). Disabled until the user explicitly enables it.
"""

from __future__ import annotations

from ...core.models import ProviderKind, Vertical
from ..base import NotYetImplementedProvider


class FacebookMarketplaceProvider(NotYetImplementedProvider):
    name = "facebook_marketplace"
    kind = ProviderKind.BROWSER
    verticals = frozenset({Vertical.GOODS})
    description = "Facebook Marketplace local listings via your own browser session (opt-in, planned)"
    opt_in = True
    planned_approach = "playwright with user-owned session; radius search; price + distance extraction"
