"""Cross-provider deduplication and product matching.

Two offers are the "same listing" if they share a strong identifier (UPC/EAN/ASIN) *and* seller,
or if their URLs match. Offers for the same *product* from different sellers are kept separate
(that's the whole point) but tagged with a shared `product_key` so history can track them together.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from .models import Offer

_STRONG_IDS = ("upc", "ean", "gtin", "asin", "isbn")


def product_key(offer: Offer) -> str:
    for k in _STRONG_IDS:
        if v := offer.identifiers.get(k):
            return f"{k}:{v}"
    if offer.vertical.value != "goods":
        return f"{offer.vertical.value}:{_slug(offer.title)}"
    return "title:" + _slug(offer.title)


def _slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in {"the", "a", "an", "for", "with", "and", "new", "free", "shipping"}]
    return "-".join(tokens[:12])


def dedupe(offers: list[Offer]) -> list[Offer]:
    """Drop exact repeats: same listing (product + seller) at the same or a higher price.

    URLs alone are not a listing identity: browser-backed sources emit many offers that all point at
    one results page, so the URL only participates together with the product key and seller.
    """
    seen_exact: set[tuple[str, str, str]] = set()
    seen_listing: set[tuple[str, str]] = set()
    out: list[Offer] = []
    for o in offers:
        key = (product_key(o), o.seller.name.lower())
        exact = (o.url or "", *key)
        if exact in seen_exact:
            continue
        if key in seen_listing and o.base_price.amount >= _min_price_for(out, key):
            continue
        seen_exact.add(exact)
        seen_listing.add(key)
        out.append(o)
    return out


def _min_price_for(offers: list[Offer], key: tuple[str, str]) -> float:
    prices = [float(o.base_price.amount) for o in offers if (product_key(o), o.seller.name.lower()) == key]
    return min(prices) if prices else float("inf")


def matches_query(title: str, item: str, threshold: int = 55) -> bool:
    """Loose relevance filter so a search for 'xm5 headphones' doesn't rank an 'xm5 case' first."""
    return fuzz.token_set_ratio(title.lower(), item.lower()) >= threshold
