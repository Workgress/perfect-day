from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from app.core.config import get_settings
from app.core.redis import create_redis
from app.db.session import create_engine
from app.modules.meta.router import router as meta_router

CACHE_DEFAULT_EXPIRE_SECONDS = 3600


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.redis = create_redis(settings)
    FastAPICache.init(
        RedisBackend(app.state.redis),
        prefix="pd",
        expire=CACHE_DEFAULT_EXPIRE_SECONDS,
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.include_router(meta_router, prefix=settings.api_prefix)
    return app


app = create_app()
