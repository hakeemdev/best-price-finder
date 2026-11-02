"""Runtime settings. All values can be supplied via environment variables prefixed with PF_."""

from __future__ import annotations

from functools import lru_cache

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
    anthropic_api_key: str | None = None

    # Networking / orchestration
    http_timeout_seconds: float = 20.0
    provider_timeout_seconds: float = 30.0
    max_concurrent_providers: int = 8
    user_agent: str = "pricefinder/0.1 (+https://github.com/hakeemdev/best-price-finder)"

    # Savings data
    cards_catalog_path: str = "data/cards.yaml"
    coupons_path: str = "data/coupons.yaml"
    cashback_portals_path: str = "data/cashback.yaml"

    # Rewards valuation defaults (cents per point) when a card does not specify
    default_point_value_cents: float = Field(default=1.0, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
