from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi_cache.decorator import cache
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter
from redis.asyncio import Redis

from app.core.config import get_settings
from app.main import CACHE_DEFAULT_EXPIRE_SECONDS, app
from app.modules.biorhythm.cache import BiorhythmCache

pytestmark = pytest.mark.docker

UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1"

LiveApp = Callable[..., AbstractAsyncContextManager[FastAPI]]


@pytest.fixture
def live_app(postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch) -> LiveApp:
    @asynccontextmanager
    async def start(redis: str = redis_url) -> AsyncIterator[FastAPI]:
        monkeypatch.setenv("DATABASE_URL", postgres_url)
        monkeypatch.setenv("REDIS_URL", redis)
        get_settings.cache_clear()
        try:
            async with app.router.lifespan_context(app):
                yield app
        finally:
            get_settings.cache_clear()

    return start


async def _get(target: FastAPI, path: str) -> tuple[int, object]:
    async with AsyncClient(transport=ASGITransport(app=target), base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_ready_with_real_services(live_app: LiveApp) -> None:
    async with live_app() as running:
        status, body = await _get(running, "/api/v1/ready")

    assert status == 200
    assert body == {"db": "ok", "redis": "ok"}


async def test_ready_reports_unreachable_redis(live_app: LiveApp) -> None:
    async with live_app(redis=UNREACHABLE_REDIS_URL) as running:
        status, body = await _get(running, "/api/v1/ready")

    assert status == 503
    assert body == {"db": "ok", "redis": "error"}


async def test_cached_responses_always_expire(live_app: LiveApp) -> None:
    probe = FastAPI()
    calls = 0

    @probe.get("/probe")
    @cache()
    async def probe_endpoint() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    async with live_app() as running:
        first = await _get(probe, "/probe")
        second = await _get(probe, "/probe")

        redis: Redis = running.state.redis
        keys = [key async for key in redis.scan_iter("pd:*")]
        ttls = [await redis.ttl(key) for key in keys]
        await redis.delete(*keys)

    assert first == second == (200, {"calls": 1})
    assert keys
    assert all(0 < ttl <= CACHE_DEFAULT_EXPIRE_SECONDS for ttl in ttls)


async def test_biorhythm_cache_uses_live_redis_and_separate_ttl(live_app: LiveApp) -> None:
    async with live_app() as running:
        cache: BiorhythmCache = running.state.biorhythm_cache
        redis: Redis = running.state.redis
        key = f"{cache.prefix}:bio:test:{uuid4()}"
        calls = 0

        def calculate() -> int:
            nonlocal calls
            calls += 1
            return 42

        try:
            assert await cache.get_or_compute(key, TypeAdapter(int), calculate) == 42
            assert await cache.get_or_compute(key, TypeAdapter(int), calculate) == 42
            assert calls == 1
            ttl = await redis.ttl(key)
            assert CACHE_DEFAULT_EXPIRE_SECONDS < ttl <= 86400
        finally:
            await redis.delete(key)
