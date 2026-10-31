from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi_cache.decorator import cache
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.core.config import get_settings
from app.main import CACHE_DEFAULT_EXPIRE_SECONDS, app

pytestmark = pytest.mark.docker

UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1"
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://test:test@127.0.0.1:1/test"

LiveApp = Callable[..., AbstractAsyncContextManager[FastAPI]]


@pytest.fixture
def live_app(postgres_url: str, redis_url: str, monkeypatch: pytest.MonkeyPatch) -> LiveApp:
    @asynccontextmanager
    async def start(
        redis: str = redis_url,
        database: str = postgres_url,
    ) -> AsyncIterator[FastAPI]:
        monkeypatch.setenv("DATABASE_URL", database)
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


async def test_ready_reports_unreachable_database(live_app: LiveApp) -> None:
    async with live_app(database=UNREACHABLE_DATABASE_URL) as running:
        status, body = await _get(running, "/api/v1/ready")

    assert status == 503
    assert body == {"db": "error", "redis": "ok"}


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
