import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from hashlib import sha256
from uuid import UUID

from fastapi_cache.types import Backend
from pydantic import TypeAdapter, ValidationError
from redis.exceptions import RedisError

from app.modules.biorhythm.config import (
    ALGORITHM_VERSION,
    BIO_CACHE_TIMEOUT_SECONDS,
    BIO_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)
type CacheParameters = Mapping[str, str | int | bool | None]


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def build_cache_key(
    user_id: UUID,
    birth_data: CacheParameters,
    timezone: str,
    request: CacheParameters,
    *,
    prefix: str = "pd",
    algorithm_version: str = ALGORITHM_VERSION,
) -> str:
    birth_hash = sha256(_json_bytes(dict(birth_data))).hexdigest()
    timezone_hash = sha256(timezone.encode("utf-8")).hexdigest()
    request_hash = sha256(_json_bytes(dict(request))).hexdigest()
    return f"{prefix}:bio:{algorithm_version}:{user_id}:{birth_hash}:{timezone_hash}:{request_hash}"


def _encode[T](value: T, adapter: TypeAdapter[T]) -> bytes:
    # JSON-native output and allow_nan=False also reject nonfinite numbers
    # rather than letting a serializer silently replace them with null.
    return _json_bytes(adapter.dump_python(value, mode="json", warnings="error"))


class BiorhythmCache:
    def __init__(
        self,
        backend: Backend,
        *,
        prefix: str = "pd",
        timeout_seconds: float = BIO_CACHE_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Тайм-аут кэша должен быть положительным")
        self.backend = backend
        self.prefix = prefix
        self.timeout_seconds = timeout_seconds

    async def get_or_compute[T](
        self, key: str, adapter: TypeAdapter[T], compute: Callable[[], T]
    ) -> T:
        available = True
        try:
            async with asyncio.timeout(self.timeout_seconds):
                raw = await self.backend.get(key)
        except (RedisError, OSError, TimeoutError):
            # Skip the write as well: a failed read must not add another
            # network wait to a cheap, local calculation.
            available = False
            raw = None
            logger.warning("Biorhythm cache unavailable during read")
        if raw is not None:
            try:
                cached = adapter.validate_json(raw)
                _encode(cached, adapter)  # Check finite floats after typed decoding too.
                return cached
            except (ValidationError, ValueError):
                logger.warning("Invalid biorhythm cache entry; recalculating")

        # Calculation and serialization errors are deliberately outside the
        # Redis exception handlers, so programming/data errors remain visible.
        value = compute()
        encoded = _encode(value, adapter)
        if available:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    await self.backend.set(key, encoded, expire=BIO_CACHE_TTL_SECONDS)
            except (RedisError, OSError, TimeoutError):
                logger.warning("Biorhythm cache unavailable during write")
        return value
