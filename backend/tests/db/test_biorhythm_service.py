import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock, LocalTimeError
from app.modules.biorhythm import engine
from app.modules.biorhythm.cache import BiorhythmCache
from app.modules.biorhythm.service import BiorhythmService, OnboardingRequiredError
from app.modules.biorhythm.types import (
    BiorhythmSnapshot,
    CriticalDays,
    Forecast,
    ForecastPeriod,
    Step,
)
from app.modules.users.models import Chronotype, User, UserProfile
from app.modules.users.schemas import ProfilePatch
from app.modules.users.service import ProfileService
from tests.db.factories import make_user

pytestmark = pytest.mark.docker
NOW = datetime(2026, 11, 7, 10, tzinfo=UTC)
CLOCK = FrozenClock(NOW)


@pytest.fixture
async def cache(redis_url: str) -> AsyncIterator[BiorhythmCache]:
    client: Redis = Redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
    cache = BiorhythmCache(RedisBackend(client), prefix=f"test:{uuid4()}")
    try:
        yield cache
    finally:
        keys = [key async for key in client.scan_iter(f"{cache.prefix}:bio:*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def completed_user(session: AsyncSession, email: str = "user@example.ru") -> User:
    user = await make_user(session, email)
    await ProfileService(session, CLOCK).update_profile(
        user.id,
        ProfilePatch.model_validate(
            {"birth_date": "2000-01-01", "birth_time": "12:00", "chronotype": "dove"}
        ),
    )
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.onboarding_completed_at = NOW
    await session.flush()
    return user


async def keys(cache: BiorhythmCache) -> set[bytes]:
    backend = cache.backend
    assert isinstance(backend, RedisBackend)
    return {key async for key in backend.redis.scan_iter(f"{cache.prefix}:bio:*")}


async def request(
    service: BiorhythmService, user_id: UUID, kind: str
) -> BiorhythmSnapshot | Forecast | CriticalDays:
    if kind == "snapshot":
        return await service.get_snapshot(user_id, NOW)
    if kind == "series":
        return await service.get_series(user_id, date(2026, 11, 7), date(2026, 11, 8))
    if kind == "forecast":
        return await service.get_forecast(user_id, ForecastPeriod.WEEK)
    return await service.get_critical_days(user_id, date(2026, 11, 1), date(2026, 11, 30))


@pytest.mark.parametrize("kind", ["snapshot", "series", "forecast", "critical_days"])
async def test_miss_and_hit_have_identical_types_and_data_with_real_redis(
    session: AsyncSession, cache: BiorhythmCache, kind: str
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    method = (
        "snapshot"
        if kind == "snapshot"
        else "critical_info"
        if kind == "critical_days"
        else "forecast"
    )
    with patch.object(engine, method, wraps=getattr(engine, method)) as calculate:
        first = await request(service, user.id, kind)
        count = calculate.call_count
        assert count > 0
        second = await request(service, user.id, kind)
        assert first == second and type(first) is type(second)
        assert calculate.call_count == count
    stored = await keys(cache)
    assert len(stored) == 1
    backend = cache.backend
    assert isinstance(backend, RedisBackend)
    key = next(iter(stored))
    assert 86390 <= await backend.redis.ttl(key) <= 86400
    raw = await backend.redis.get(key)
    assert raw is not None and isinstance(json.loads(raw), dict)


@pytest.mark.parametrize(
    "change",
    [
        {"birth_date": "2000-01-02"},
        {"birth_time": "13:00"},
        {"birth_tz": "Europe/Moscow"},
        {"birth_time_known": False},
        {"timezone": "Asia/Yekaterinburg"},
    ],
)
async def test_birth_or_timezone_change_uses_new_key_without_deleting_old_entry(
    session: AsyncSession, cache: BiorhythmCache, change: dict[str, Any]
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    await service.get_snapshot(user.id, NOW)
    original_keys = await keys(cache)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch.model_validate(change)
    )
    await service.get_snapshot(user.id, NOW)
    changed_keys = await keys(cache)
    assert len(changed_keys) == 2 and original_keys < changed_keys


async def test_unrelated_profile_fields_do_not_invalidate_cycles(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    before = await service.get_snapshot(user.id, NOW)
    original_keys = await keys(cache)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch(display_name="Ирина", chronotype=Chronotype.OWL, sleep_time=time(1))
    )
    with patch.object(engine, "snapshot", side_effect=AssertionError("unexpected calculation")):
        assert await service.get_snapshot(user.id, NOW) == before
    assert await keys(cache) == original_keys


async def test_users_have_separate_cache_entries(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    first = await completed_user(session, "first@example.ru")
    second = await completed_user(session, "second@example.ru")
    service = BiorhythmService(session, cache, CLOCK)
    assert await service.get_snapshot(first.id, NOW) == await service.get_snapshot(second.id, NOW)
    assert len(await keys(cache)) == 2


@pytest.mark.parametrize(
    "state", ["no_profile", "incomplete", "inactive", "deleted", "onboarding_reset"]
)
async def test_profile_guard_precedes_cache_access(
    session: AsyncSession, cache: BiorhythmCache, state: str
) -> None:
    if state == "no_profile":
        user = await make_user(session)
    else:
        user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    if state in {"inactive", "deleted", "onboarding_reset"}:
        await service.get_snapshot(user.id, NOW)
    if state in {"incomplete", "onboarding_reset"}:
        profile = await session.get(UserProfile, user.id)
        assert profile is not None
        profile.onboarding_completed_at = None
    elif state == "inactive":
        user.is_active = False
    elif state == "deleted":
        user.deleted_at = NOW
    await session.flush()
    with (
        patch.object(cache.backend, "get", side_effect=AssertionError("cache read before guard")),
        pytest.raises(OnboardingRequiredError),
    ):
        await service.get_snapshot(user.id, NOW)


@dataclass
class MutableClock:
    instant: datetime
    calls: int = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.instant


async def test_now_resolves_exact_moment_once_and_normalizes_equivalent_offsets(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    clock = MutableClock(NOW)
    service = BiorhythmService(session, cache, clock)
    original = await service.get_snapshot(user.id)
    assert original.at == NOW and clock.calls == 1
    assert (
        await service.get_snapshot(user.id, NOW.astimezone(ZoneInfo("Asia/Yekaterinburg")))
        == original
    )
    assert clock.calls == 1 and len(await keys(cache)) == 1
    clock.instant += timedelta(microseconds=1)
    assert (await service.get_snapshot(user.id)).at == clock.instant
    assert clock.calls == 2 and len(await keys(cache)) == 2


async def test_forecast_key_changes_at_local_midnight_not_every_second(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch(timezone="Asia/Yekaterinburg")
    )
    clock = MutableClock(datetime(2026, 11, 7, 18, 58, tzinfo=UTC))
    service = BiorhythmService(session, cache, clock)
    first = await service.get_forecast(user.id, ForecastPeriod.WEEK)
    clock.instant += timedelta(minutes=1)
    assert await service.get_forecast(user.id, ForecastPeriod.WEEK) == first
    assert len(await keys(cache)) == 1
    clock.instant += timedelta(minutes=2)
    second = await service.get_forecast(user.id, ForecastPeriod.WEEK)
    assert first.start == date(2026, 11, 7) and second.start == date(2026, 11, 8)
    assert clock.calls == 3 and len(await keys(cache)) == 2


async def test_range_step_period_and_operation_have_distinct_keys(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    day = date(2026, 11, 7)
    await service.get_series(user.id, day, day, Step.DAY)
    await service.get_series(user.id, day, day, Step.HOUR)
    await service.get_series(user.id, day, day + timedelta(days=1), Step.DAY)
    await service.get_forecast(user.id, ForecastPeriod.DAY)
    await service.get_forecast(user.id, ForecastPeriod.WEEK)
    await service.get_forecast(user.id, ForecastPeriod.MONTH)
    await service.get_critical_days(user.id, day, day)
    assert len(await keys(cache)) == 7


@pytest.mark.parametrize("kind", ["series", "critical_days"])
@pytest.mark.parametrize("days", [-1, 63])
async def test_invalid_range_is_rejected_before_cache(
    session: AsyncSession, cache: BiorhythmCache, kind: str, days: int
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    start = date(2026, 11, 7)
    method = service.get_series if kind == "series" else service.get_critical_days
    with (
        patch.object(
            cache.backend, "get", side_effect=AssertionError("invalid request read cache")
        ),
        pytest.raises(engine.ForecastValidationError),
    ):
        await method(user.id, start, start + timedelta(days=days - 1))


async def test_before_birth_rules_use_actual_points_and_critical_day_start(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    birth = datetime(2000, 1, 1, 12, tzinfo=UTC)
    assert (await service.get_snapshot(user.id, birth)).critical.level == 3
    assert len((await service.get_series(user.id, birth.date(), birth.date())).points) == 1
    with patch.object(
        cache.backend, "get", side_effect=AssertionError("invalid request read cache")
    ):
        with pytest.raises(engine.ForecastValidationError, match="до момента рождения"):
            await service.get_snapshot(user.id, birth - timedelta(microseconds=1))
        with pytest.raises(engine.ForecastValidationError, match="до момента рождения"):
            await service.get_series(user.id, birth.date(), birth.date(), Step.HOUR)
        with pytest.raises(engine.ForecastValidationError, match="до момента рождения"):
            await service.get_critical_days(user.id, birth.date(), birth.date())
        with pytest.raises(engine.ForecastValidationError, match="до момента рождения"):
            await BiorhythmService(session, cache, FrozenClock(birth)).get_forecast(
                user.id, ForecastPeriod.DAY
            )


async def test_nonexistent_noon_does_not_block_critical_days(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch(timezone="Africa/Khartoum")
    )
    service = BiorhythmService(session, cache, CLOCK)
    day = date(2000, 1, 15)
    with pytest.raises(LocalTimeError):
        await service.get_series(user.id, day, day)
    assert (await service.get_critical_days(user.id, day, day)).start == day


async def test_unavailable_redis_still_returns_calculation(session: AsyncSession) -> None:
    user = await completed_user(session)
    client: Redis = Redis.from_url(
        "redis://127.0.0.1:1", socket_connect_timeout=0.01, socket_timeout=0.01
    )
    try:
        service = BiorhythmService(session, BiorhythmCache(RedisBackend(client)), CLOCK)
        result = await service.get_snapshot(user.id, NOW)
        assert result.cycles == engine.snapshot(datetime(2000, 1, 1, 12, tzinfo=UTC), NOW).cycles
    finally:
        await client.aclose()


async def test_missing_user_is_rejected_before_cache(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    service = BiorhythmService(session, cache, CLOCK)
    with (
        patch.object(cache.backend, "get", side_effect=AssertionError("missing user read cache")),
        pytest.raises(OnboardingRequiredError),
    ):
        await service.get_snapshot(uuid4(), NOW)


@pytest.mark.parametrize("field", ["start", "end"])
async def test_datetime_range_bounds_are_rejected_before_cache(
    session: AsyncSession, cache: BiorhythmCache, field: str
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    bounds = {"start": date(2026, 11, 7), "end": date(2026, 11, 8)}
    bounds[field] = NOW
    with (
        patch.object(cache.backend, "get", side_effect=AssertionError("invalid range read cache")),
        pytest.raises(engine.ForecastValidationError) as error,
    ):
        await service.get_series(user.id, **bounds)
    assert error.value.code == "INVALID_DATE"


async def test_empty_critical_days_list_round_trips_through_cache(
    session: AsyncSession, cache: BiorhythmCache
) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    day = date(2000, 1, 2)
    first = await service.get_critical_days(user.id, day, day)
    assert first.days == ()
    assert await service.get_critical_days(user.id, day, day) == first


async def test_expired_entry_is_recomputed(session: AsyncSession, cache: BiorhythmCache) -> None:
    user = await completed_user(session)
    service = BiorhythmService(session, cache, CLOCK)
    first = await service.get_snapshot(user.id, NOW)
    key = next(iter(await keys(cache)))
    backend = cache.backend
    assert isinstance(backend, RedisBackend)
    await backend.redis.pexpire(key, 0)
    assert await backend.redis.get(key) is None
    with patch.object(engine, "snapshot", wraps=engine.snapshot) as calculate:
        assert await service.get_snapshot(user.id, NOW) == first
        calculate.assert_called_once()
    assert 86390 <= await backend.redis.ttl(key) <= 86400
