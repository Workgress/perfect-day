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
from app.modules.auth.router import router as auth_router
from app.modules.biorhythm.cache import BiorhythmCache
from app.modules.biorhythm.router import router as biorhythm_router
from app.modules.meta.router import router as meta_router
from app.modules.schedule.router import router as onboarding_router
from app.modules.tasks.router import router as tasks_router
from app.modules.users.router import router as profile_router

CACHE_DEFAULT_EXPIRE_SECONDS = 3600
CACHE_PREFIX = "pd"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.engine = create_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.redis = create_redis(settings)
    cache_backend = RedisBackend(app.state.redis)
    FastAPICache.init(
        cache_backend,
        prefix=CACHE_PREFIX,
        expire=CACHE_DEFAULT_EXPIRE_SECONDS,
    )
    app.state.biorhythm_cache = BiorhythmCache(cache_backend, prefix=CACHE_PREFIX)
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
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(profile_router, prefix=settings.api_prefix)
    app.include_router(onboarding_router, prefix=settings.api_prefix)
    app.include_router(biorhythm_router, prefix=settings.api_prefix)
    app.include_router(tasks_router, prefix=settings.api_prefix)
    return app


app = create_app()
