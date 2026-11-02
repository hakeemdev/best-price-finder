from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..config import get_settings
from ..core.models import Money, PricedOffer, Query, UserProfile
from ..core.normalize import product_key
from .models import Base, ObservedOffer, ProfileRecord, SearchRun


class Repository:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or get_settings().database_url
        if url.startswith("sqlite:///"):
            path = url.removeprefix("sqlite:///")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url.endswith(":memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._session()

    # -- writes ---------------------------------------------------------------

    def record_search(self, query: Query, offers: list[PricedOffer], providers: list[str]) -> int:
        with self.session() as s:
            run = SearchRun(
                raw_query=query.raw,
                vertical=query.vertical.value,
                item=query.item,
                query_json=query.model_dump(mode="json"),
                providers=providers,
            )
            for po in offers:
                run.offers.append(
                    ObservedOffer(
                        product_key=product_key(po.offer),
                        offer_id=po.offer.id,
                        provider=po.offer.provider,
                        vertical=po.offer.vertical.value,
                        title=po.offer.title,
                        seller=po.offer.seller.name,
                        url=po.offer.url,
                        currency=po.effective_total.currency,
                        sticker_total=float(po.sticker_total.amount),
                        effective_total=float(po.effective_total.amount),
                        guaranteed_total=float(po.guaranteed_total.amount),
                        condition=po.offer.condition.value,
                        adjustments_json=[a.model_dump(mode="json") for a in po.adjustments],
                        offer_json=po.offer.model_dump(mode="json", exclude={"raw"}),
                    )
                )
            s.add(run)
            s.commit()
            return run.id

    def save_profile(self, profile: UserProfile) -> None:
        with self.session() as s:
            rec = s.get(ProfileRecord, profile.id) or ProfileRecord(id=profile.id, profile_json={})
            rec.profile_json = profile.model_dump(mode="json")
            s.add(rec)
            s.commit()

    # -- reads ----------------------------------------------------------------

    def get_profile(self, profile_id: str) -> UserProfile | None:
        with self.session() as s:
            rec = s.get(ProfileRecord, profile_id)
            return UserProfile.model_validate(rec.profile_json) if rec else None

    def best_ever(self, key: str) -> Money | None:
        with self.session() as s:
            row = s.execute(
                select(ObservedOffer.effective_total, ObservedOffer.currency)
                .where(ObservedOffer.product_key == key)
                .order_by(ObservedOffer.effective_total.asc())
                .limit(1)
            ).first()
            return Money(amount=Decimal(str(row[0])), currency=row[1]) if row else None

    def history(self, item_substring: str, *, days: int = 90, limit: int = 200) -> list[ObservedOffer]:
        since = datetime.now(UTC) - timedelta(days=days)
        with self.session() as s:
            return list(
                s.execute(
                    select(ObservedOffer)
                    .where(ObservedOffer.observed_at >= since)
                    .where(func.lower(ObservedOffer.title).contains(item_substring.lower()))
                    .order_by(ObservedOffer.observed_at.desc())
                    .limit(limit)
                ).scalars()
            )

    def recent_runs(self, limit: int = 20) -> list[SearchRun]:
        with self.session() as s:
            return list(s.execute(select(SearchRun).order_by(SearchRun.created_at.desc()).limit(limit)).scalars())
