"""SQLAlchemy tables: search runs, observed offers (price history), and user profiles.

Every observed offer is appended, never updated, so `best_ever` and trend queries are trivial.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_query: Mapped[str] = mapped_column(Text)
    vertical: Mapped[str] = mapped_column(String(32), index=True)
    item: Mapped[str] = mapped_column(Text, index=True)
    query_json: Mapped[dict] = mapped_column(JSON)
    providers: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    offers: Mapped[list[ObservedOffer]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ObservedOffer(Base):
    __tablename__ = "observed_offers"
    __table_args__ = (Index("ix_observed_product_time", "product_key", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id"), index=True)
    product_key: Mapped[str] = mapped_column(String(256), index=True)
    offer_id: Mapped[str] = mapped_column(String(256))
    provider: Mapped[str] = mapped_column(String(64), index=True)
    vertical: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    seller: Mapped[str] = mapped_column(String(256))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(8))
    sticker_total: Mapped[float] = mapped_column(Float)
    effective_total: Mapped[float] = mapped_column(Float, index=True)
    guaranteed_total: Mapped[float] = mapped_column(Float)
    condition: Mapped[str] = mapped_column(String(32))
    adjustments_json: Mapped[list] = mapped_column(JSON)
    offer_json: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[SearchRun] = relationship(back_populates="offers")


class ProfileRecord(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
