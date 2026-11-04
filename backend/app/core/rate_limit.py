from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import AppError
from app.core.security import generate_token, hash_token

_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def rate_limit_key(scope: str, identity: str) -> str:
    return f"pd:auth:{scope}:{hash_token(identity)}"


def unavailable() -> AppError:
    return AppError(503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен")


class AuthRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def enforce(self, scope: str, identity: str, limit: int, seconds: int) -> None:
        try:
            count, ttl = await self.redis.eval(
                _LIMIT_SCRIPT, 1, rate_limit_key(scope, identity), seconds
            )
        except RedisError:
            raise unavailable() from None
        if int(count) > limit:
            raise AppError(
                429,
                "RATE_LIMIT_EXCEEDED",
                "Превышен лимит запросов",
                headers={"Retry-After": str(max(int(ttl), 1))},
            )

    async def start_verification_cooldown(self, email: str, *, initial: bool = False) -> str:
        key = rate_limit_key("verification-email", email)
        lease = generate_token()
        try:
            acquired = await self.redis.set(key, lease, ex=60, nx=not initial)
            if not acquired:
                ttl = await self.redis.ttl(key)
                raise AppError(
                    429,
                    "RATE_LIMIT_EXCEEDED",
                    "Повторная отправка доступна не чаще одного раза в минуту",
                    headers={"Retry-After": str(max(ttl, 1))},
                )
        except RedisError:
            raise unavailable() from None
        return lease

    async def release_verification_cooldown(self, email: str, lease: str) -> None:
        try:
            await self.redis.eval(
                _RELEASE_SCRIPT, 1, rate_limit_key("verification-email", email), lease
            )
        except RedisError:
            return
