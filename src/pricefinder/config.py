"""Runtime settings. All values can be supplied via environment variables prefixed with PF_."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PF_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/pricefinder.db"
    home_postal_code: str | None = None
    home_country: str = "US"
    default_currency: str = "USD"

    # Provider credentials (all optional)
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    serpapi_key: str | None = None
    bestbuy_api_key: str | None = None
    walmart_consumer_id: str | None = None
    walmart_private_key_path: str | None = None  # PEM file from walmart.io
    walmart_key_version: str = "1"

    # Query understanding. "auto" uses the LLM parser when an Anthropic key is available.
    anthropic_api_key: str | None = None
    query_parser: Literal["auto", "rules", "llm"] = "auto"
    llm_model: str = "claude-opus-5-5"

    # Networking / orchestration
    http_timeout_seconds: float = 20.0
    provider_timeout_seconds: float = 30.0
    max_concurrent_providers: int = 8
    user_agent: str = "pricefinder/0.1 (+https://github.com/hakeemdev/best-price-finder)"

    # Savings data
    cards_catalog_path: str = "data/cards.yaml"
    coupons_path: str = "data/coupons.yaml"
    cashback_portals_path: str = "data/cashback.yaml"
    rental_codes_path: str = "data/rental_codes.yaml"
    rental_locations_path: str = "data/rental_locations.yaml"
    browser_providers_enabled: bool = True  # headless-browser adapters (Sixt, Kayak); needs pricefinder[browser]
    browser_headless: bool = True  # False = assisted mode: a visible window where you can pass a site's security check
    memberships_path: str = "data/memberships.yaml"
    local_radius_km: float = 40.0

    # Rewards valuation defaults (cents per point) when a card does not specify
    default_point_value_cents: float = Field(default=1.0, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
