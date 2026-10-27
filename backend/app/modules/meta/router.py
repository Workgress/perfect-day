import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.redis import get_redis
from app.db.session import get_engine

router = APIRouter(tags=["meta"])

PROBE_TIMEOUT_SECONDS = 2


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _probe_db(engine: AsyncEngine) -> str:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"


async def _probe_redis(redis: Redis) -> str:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await redis.ping()
    except Exception:
        return "error"
    return "ok"


@router.get("/ready")
async def ready(
    response: Response,
    engine: Annotated[AsyncEngine, Depends(get_engine)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict[str, str]:
    db_status, redis_status = await asyncio.gather(_probe_db(engine), _probe_redis(redis))
    checks = {"db": db_status, "redis": redis_status}
    if any(value != "ok" for value in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
