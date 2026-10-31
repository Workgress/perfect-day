from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.redis import get_redis
from app.db.session import get_engine
from app.main import app


class FakeConnection:
    async def execute(self, *_: Any) -> None:
        return None


class FakeEngine:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[FakeConnection]:
        if not self.healthy:
            raise OSError("connection refused")
        yield FakeConnection()


class FakeRedis:
    def __init__(self, healthy: bool) -> None:
        self.healthy = healthy

    async def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("connection refused")
        return True


@pytest.fixture
def override_deps() -> Iterator[Any]:
    def apply(db_ok: bool, redis_ok: bool) -> None:
        app.dependency_overrides[get_engine] = lambda: FakeEngine(db_ok)
        app.dependency_overrides[get_redis] = lambda: FakeRedis(redis_ok)

    yield apply
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("db_ok", "redis_ok", "expected_status", "expected_body"),
    [
        (True, True, 200, {"db": "ok", "redis": "ok"}),
        (True, False, 503, {"db": "ok", "redis": "error"}),
        (False, True, 503, {"db": "error", "redis": "ok"}),
        (False, False, 503, {"db": "error", "redis": "error"}),
    ],
)
async def test_ready(
    override_deps: Any,
    db_ok: bool,
    redis_ok: bool,
    expected_status: int,
    expected_body: dict[str, str],
) -> None:
    override_deps(db_ok, redis_ok)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/ready")

    assert response.status_code == expected_status
    assert response.json() == expected_body
