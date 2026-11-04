from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from app.core.config import get_settings
from app.core.errors import ERROR_RESPONSES, register_error_handlers
from app.core.redis import create_redis
from app.db.session import create_engine, create_sessionmaker
from app.modules.meta.router import router as meta_router

CACHE_DEFAULT_EXPIRE_SECONDS = 3600


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
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
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(meta_router, prefix=settings.api_prefix)
    return app


app = create_app()
