"""HTTP API. `pf serve` or `uvicorn pricefinder.api.app:app`."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi import Query as QParam
from pydantic import BaseModel

from .. import __version__
from ..config import get_settings
from ..core.engine import SearchEngine
from ..core.models import Query, SearchResult, UserProfile, Vertical
from ..core.query import RuleBasedQueryParser
from ..core.registry import default_registry
from ..storage.repository import Repository

app = FastAPI(title="pricefinder", version=__version__)
_repo: Repository | None = None


def repo() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository()
    return _repo


class SearchRequest(BaseModel):
    text: str | None = None
    query: Query | None = None
    providers: list[str] | None = None
    profile_id: str = "default"


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/providers")
def providers() -> list[dict]:
    s = get_settings()
    return [
        {
            "name": p.name,
            "kind": p.kind.value,
            "verticals": sorted(v.value for v in p.verticals),
            "available": p.is_available(s),
            "missing_settings": p.missing_settings(s),
            "opt_in": p.opt_in,
            "description": p.description,
        }
        for p in default_registry().all()
    ]


@app.post("/search", response_model=SearchResult)
async def search(req: SearchRequest) -> SearchResult:
    if req.query is None and not req.text:
        raise HTTPException(400, "provide `text` or `query`")
    query = req.query or RuleBasedQueryParser().parse(req.text or "")
    query.profile_id = req.profile_id
    engine = SearchEngine(repository=repo())
    return await engine.search(query, providers=req.providers)


@app.get("/search", response_model=SearchResult)
async def search_get(
    q: str = QParam(..., min_length=1), vertical: Vertical | None = None, profile_id: str = "default"
) -> SearchResult:
    query = RuleBasedQueryParser().parse(q)
    if vertical:
        query.vertical = vertical
    query.profile_id = profile_id
    return await SearchEngine(repository=repo()).search(query)


@app.get("/history")
def history(item: str, days: int = 90, limit: int = 100) -> list[dict]:
    return [
        {
            "observed_at": r.observed_at,
            "provider": r.provider,
            "seller": r.seller,
            "title": r.title,
            "url": r.url,
            "sticker_total": r.sticker_total,
            "effective_total": r.effective_total,
            "currency": r.currency,
        }
        for r in repo().history(item, days=days, limit=limit)
    ]


@app.get("/profiles/{profile_id}", response_model=UserProfile)
def get_profile(profile_id: str) -> UserProfile:
    return repo().get_profile(profile_id) or UserProfile(id=profile_id)


@app.put("/profiles/{profile_id}", response_model=UserProfile)
def put_profile(profile_id: str, profile: UserProfile) -> UserProfile:
    profile.id = profile_id
    repo().save_profile(profile)
    return profile
