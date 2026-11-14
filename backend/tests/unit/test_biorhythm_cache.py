import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi_cache.types import Backend
from pydantic import TypeAdapter
from redis.exceptions import ConnectionError as RedisConnectionError

from app.modules.biorhythm.cache import BiorhythmCache, CacheParameters, build_cache_key
from app.modules.biorhythm.config import BIO_CACHE_TTL_SECONDS
from app.modules.biorhythm.engine import forecast
from app.modules.biorhythm.types import Forecast

USER_ID = UUID("12345678-1234-5678-1234-567812345678")
BIRTH_DATA: CacheParameters = {
    "birth_date": "2000-01-01",
    "birth_time": "12:00:00",
    "birth_time_known": True,
    "birth_tz": "UTC",
    "birth_at_utc": "2000-01-01T12:00:00.000000Z",
}
REQUEST: CacheParameters = {
    "kind": "series",
    "from": "2026-11-07",
    "to": "2026-11-08",
    "step": "day",
}


def test_key_is_canonical_and_does_not_expose_birth_data() -> None:
    key = build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST)
    reordered = build_cache_key(
        USER_ID,
        dict(reversed(list(BIRTH_DATA.items()))),
        "UTC",
        dict(reversed(list(REQUEST.items()))),
    )
    assert key == reordered
    assert key.startswith(f"pd:bio:1.0.0:{USER_ID}:")
    assert "2000-01-01" not in key and "2026-11-07" not in key


@pytest.mark.parametrize("field", list(BIRTH_DATA))
def test_every_birth_field_affects_key(field: str) -> None:
    original = build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST)
    changed = dict(BIRTH_DATA) | {field: "changed"}
    assert build_cache_key(USER_ID, changed, "UTC", REQUEST) != original


@pytest.mark.parametrize("field", list(REQUEST))
def test_every_request_field_affects_key(field: str) -> None:
    original = build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST)
    assert (
        build_cache_key(USER_ID, BIRTH_DATA, "UTC", dict(REQUEST) | {field: "changed"}) != original
    )


def test_user_timezone_version_and_prefix_have_separate_namespaces() -> None:
    original = build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST)
    assert build_cache_key(uuid4(), BIRTH_DATA, "UTC", REQUEST) != original
    assert build_cache_key(USER_ID, BIRTH_DATA, "Europe/Moscow", REQUEST) != original
    assert (
        build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST, algorithm_version="1.0.1") != original
    )
    assert build_cache_key(USER_ID, BIRTH_DATA, "UTC", REQUEST, prefix="other") != original


def make_backend() -> AsyncMock:
    backend = AsyncMock(spec=Backend)
    backend.get.return_value = None
    return backend


async def test_miss_writes_typed_json_with_24_hour_ttl_then_hit_skips_compute() -> None:
    backend = make_backend()
    cache = BiorhythmCache(backend)
    adapter = TypeAdapter(Forecast)
    result = forecast(datetime(2000, 1, 1, tzinfo=UTC), date(2026, 11, 7), 2, ZoneInfo("UTC"))
    compute = Mock(return_value=result)
    assert await cache.get_or_compute("key", adapter, compute) == result
    args = backend.set.await_args
    assert args is not None and args.kwargs["expire"] == BIO_CACHE_TTL_SECONDS == 86400
    raw = args.args[1]
    assert isinstance(raw, bytes)
    backend.get.return_value = raw
    hit = await cache.get_or_compute("key", adapter, compute)
    assert hit == result and type(hit) is Forecast
    assert hit.points[0].at.tzinfo is not None
    compute.assert_called_once()
    backend.set.assert_awaited_once()


@pytest.mark.parametrize("raw", [b"{broken", b"[]", b"NaN", b'"NaN"', b"Infinity"])
async def test_corrupt_or_nonfinite_entry_is_recomputed(raw: bytes) -> None:
    backend = make_backend()
    backend.get.return_value = raw
    result = await BiorhythmCache(backend).get_or_compute("key", TypeAdapter(float), lambda: 42.0)
    assert result == 42.0
    backend.set.assert_awaited_once_with("key", b"42.0", expire=86400)


@pytest.mark.parametrize(
    "error", [RedisConnectionError("offline"), OSError("offline"), TimeoutError()]
)
async def test_read_error_falls_back_and_does_not_attempt_write(error: Exception) -> None:
    backend = make_backend()
    backend.get.side_effect = error
    assert await BiorhythmCache(backend).get_or_compute("key", TypeAdapter(int), lambda: 7) == 7
    backend.set.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [RedisConnectionError("offline"), OSError("offline"), TimeoutError()]
)
async def test_write_error_does_not_discard_result(error: Exception) -> None:
    backend = make_backend()
    backend.set.side_effect = error
    assert await BiorhythmCache(backend).get_or_compute("key", TypeAdapter(int), lambda: 7) == 7


async def test_slow_read_has_bounded_wait() -> None:
    backend = make_backend()

    async def stalled(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    backend.get.side_effect = stalled
    async with asyncio.timeout(1):
        result = await BiorhythmCache(backend, timeout_seconds=0.01).get_or_compute(
            "key", TypeAdapter(int), lambda: 7
        )
    assert result == 7
    backend.set.assert_not_awaited()


async def test_slow_write_has_bounded_wait() -> None:
    backend = make_backend()

    async def stalled(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    backend.set.side_effect = stalled
    async with asyncio.timeout(1):
        result = await BiorhythmCache(backend, timeout_seconds=0.01).get_or_compute(
            "key", TypeAdapter(int), lambda: 7
        )
    assert result == 7


async def test_calculation_error_is_not_hidden_or_cached() -> None:
    backend = make_backend()
    compute = Mock(side_effect=ValueError("calculation failed"))
    with pytest.raises(ValueError, match="calculation failed"):
        await BiorhythmCache(backend).get_or_compute("key", TypeAdapter(int), compute)
    backend.set.assert_not_awaited()


async def test_nonfinite_result_is_not_silently_serialized_as_null() -> None:
    backend = make_backend()
    with pytest.raises(ValueError):
        await BiorhythmCache(backend).get_or_compute(
            "key", TypeAdapter(float), lambda: float("nan")
        )
    backend.set.assert_not_awaited()


async def test_cancellation_is_not_swallowed() -> None:
    backend = make_backend()
    backend.get.side_effect = asyncio.CancelledError()
    compute = Mock(return_value=7)
    with pytest.raises(asyncio.CancelledError):
        await BiorhythmCache(backend).get_or_compute("key", TypeAdapter(int), compute)
    compute.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -0.1])
def test_nonpositive_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError):
        BiorhythmCache(make_backend(), timeout_seconds=timeout)
