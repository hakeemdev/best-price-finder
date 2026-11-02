"""Shared helper for SerpApi-backed providers (Google Shopping / Flights / Hotels)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .base import ProviderContext

SERPAPI_URL = "https://serpapi.com/search.json"


async def serpapi_get(ctx: ProviderContext, **params: Any) -> dict:
    params = {k: v for k, v in params.items() if v is not None}
    params["api_key"] = ctx.settings.serpapi_key
    resp = await ctx.client().get(SERPAPI_URL, params=params)
    resp.raise_for_status()
    return resp.json()


def parse_money(value: Any) -> Decimal | None:
    """'$1,234.56' / 1234.56 / '1234' -> Decimal."""
    if value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value))
    m = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    return Decimal(m.group(0).replace(",", "")) if m else None
