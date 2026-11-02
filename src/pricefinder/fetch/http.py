"""Shared async HTTP client with retries, per-host rate limiting and an in-memory response cache."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import Settings, get_settings

log = logging.getLogger(__name__)


class HostRateLimiter:
    """Simple token-interval limiter: at most one request per `min_interval` seconds per host."""

    def __init__(self, min_interval: float = 0.25) -> None:
        self.min_interval = min_interval
        self._last: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, host: str) -> None:
        async with self._locks[host]:
            elapsed = time.monotonic() - self._last[host]
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last[host] = time.monotonic()


class HttpClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retries: int = 2,
        cache_ttl: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retries = retries
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, httpx.Response]] = {}
        self._limiter = HostRateLimiter()
        self._client = httpx.AsyncClient(
            timeout=self.settings.http_timeout_seconds,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> httpx.Response:
        req = self._client.build_request("GET", url, params=params, headers=headers)
        key = str(req.url)
        if use_cache and (hit := self._cache.get(key)) and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        resp = await self._send(req)
        if use_cache and resp.is_success:
            self._cache[key] = (time.monotonic(), resp)
        return resp

    async def post(
        self, url: str, *, data: Any = None, json: Any = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        req = self._client.build_request("POST", url, data=data, json=json, headers=headers)
        return await self._send(req)

    async def _send(self, req: httpx.Request) -> httpx.Response:
        host = urlsplit(str(req.url)).netloc
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._limiter.wait(host)
            try:
                resp = await self._client.send(req)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                log.debug("request to %s failed (attempt %d): %s", host, attempt + 1, exc)
                await asyncio.sleep(0.5 * (2**attempt))
        assert last_exc is not None
        raise last_exc
