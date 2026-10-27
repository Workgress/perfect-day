from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    client: Redis = Redis.from_url(
        settings.redis_dsn(settings.redis_cache_db),
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
    return client


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis
