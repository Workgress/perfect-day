from unittest.mock import Mock

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app import main


@pytest.mark.parametrize("request_fails", [False, True])
async def test_lifespan_releases_resources(
    monkeypatch: pytest.MonkeyPatch,
    request_fails: bool,
) -> None:
    engine = Mock(spec=AsyncEngine)
    redis = Mock(spec=Redis)
    monkeypatch.setattr(main, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(main, "create_redis", Mock(return_value=redis))
    monkeypatch.setattr(main.FastAPICache, "init", Mock())
    app = main.create_app()

    if request_fails:
        with pytest.raises(RuntimeError, match="request failed"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("request failed")
    else:
        async with app.router.lifespan_context(app):
            engine.dispose.assert_not_awaited()
            redis.aclose.assert_not_awaited()

    redis.aclose.assert_awaited_once_with()
    engine.dispose.assert_awaited_once_with()
