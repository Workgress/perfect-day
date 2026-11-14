import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi_cache.backends.redis import RedisBackend
from redis.asyncio import Redis
from sqlalchemy import func, update

from app.core.security import decode_access_token
from app.core.time import FrozenClock
from app.modules.auth.models import AuthSession
from app.modules.biorhythm import engine as bio_engine
from app.modules.biorhythm.cache import BiorhythmCache
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User, UserProfile
from tests.integration.test_profile_biorhythm_api import BIO_PATHS, ProfileAPI
from tests.integration.test_profile_biorhythm_api import alembic_config as alembic_config
from tests.integration.test_profile_biorhythm_api import auth_api as auth_api
from tests.integration.test_profile_biorhythm_api import engine as engine
from tests.integration.test_profile_biorhythm_api import migrated_url as migrated_url
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

pytestmark = pytest.mark.docker


async def cache_keys(api: ProfileAPI) -> set[bytes]:
    return {key async for key in api.api.redis.scan_iter(f"{api.cache.prefix}:bio:*")}


def calculation(path: str) -> str:
    if "/now" in path:
        return "snapshot"
    return "critical_info" if "/critical-days" in path else "forecast"


@pytest.mark.parametrize("path", BIO_PATHS)
@pytest.mark.parametrize("state", ["hit", "expired", "corrupt"])
async def test_http_cache_hit_expiration_and_corruption(
    profile_api: ProfileAPI, path: str, state: str
) -> None:
    await profile_api.complete()
    name = calculation(path)
    with patch.object(bio_engine, name, wraps=getattr(bio_engine, name)) as calculate:
        first = await profile_api.get(path)
        assert first.status_code == 200
        calls = calculate.call_count
        assert calls > 0
        stored = await cache_keys(profile_api)
        assert len(stored) == 1
        key = next(iter(stored))
        redis = profile_api.api.redis
        assert 86390 <= await redis.ttl(key) <= 86400
        if state == "expired":
            assert await redis.pexpire(key, 1)
            await asyncio.sleep(0.02)
            assert not await redis.exists(key)
        elif state == "corrupt":
            await redis.set(key, b"{invalid-json", ex=86400)

        second = await profile_api.get(path)
        assert second.status_code == 200
        assert first.json() == second.json()
        assert calculate.call_count == (calls if state == "hit" else calls * 2)
        assert await cache_keys(profile_api) == stored
        assert json.loads(await redis.get(key)) == first.json()
        assert 86390 <= await redis.ttl(key) <= 86400


@pytest.mark.parametrize("path", BIO_PATHS)
@pytest.mark.parametrize(
    "change",
    [
        {"birth_date": "2000-01-02"},
        {"birth_time": "13:00:00"},
        {"birth_time": None},
        {"timezone": "Pacific/Kiritimati"},
    ],
)
async def test_profile_patch_invalidates_each_biorhythm_operation(
    profile_api: ProfileAPI, path: str, change: dict[str, Any]
) -> None:
    await profile_api.complete()
    first = await profile_api.get(path)
    assert first.status_code == 200
    original_keys = await cache_keys(profile_api)
    updated = await profile_api.patch(change)
    assert updated.status_code == 200
    assert updated.json()["onboarding"]["completed_at"] is not None
    second = await profile_api.get(path)
    assert second.status_code == 200
    assert len(await cache_keys(profile_api)) == 2
    assert original_keys < await cache_keys(profile_api)
    assert (await profile_api.get(path)).json() == second.json()
    if "timezone" in change:
        assert second.json()["timezone"] == change["timezone"]
    if change == {"birth_time": None}:
        # Same noon calculation, but the known/unknown flag is part of the key.
        assert second.json() == first.json()


@pytest.mark.parametrize("path", BIO_PATHS)
async def test_chronotype_and_sleep_patch_preserve_cached_cycles(
    profile_api: ProfileAPI, path: str
) -> None:
    await profile_api.complete()
    first = await profile_api.get(path)
    assert first.status_code == 200
    original_keys = await cache_keys(profile_api)
    assert (
        await profile_api.patch({"chronotype": "owl", "sleep_time": "01:00:00"})
    ).status_code == 200
    with patch.object(
        bio_engine, calculation(path), side_effect=AssertionError("unexpected compute")
    ):
        cached = await profile_api.get(path)
    assert cached.status_code == 200
    assert cached.json() == first.json()
    assert await cache_keys(profile_api) == original_keys


@pytest.mark.parametrize("path", BIO_PATHS)
async def test_completed_users_with_identical_profiles_have_separate_cache_entries(
    profile_api: ProfileAPI, path: str
) -> None:
    await profile_api.complete()
    first = await profile_api.get(path)
    assert first.status_code == 200
    email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await profile_api.api.register(email)).status_code == 202
    verified = await profile_api.api.verify(profile_api.api.publisher.messages[-1][1])
    assert verified.status_code == 200
    token = verified.json()["access_token"]
    second_user_id = decode_access_token(token, profile_api.api.settings).sub
    other = ProfileAPI(
        profile_api.api, token, second_user_id, profile_api.events, profile_api.cache
    )
    await other.complete()
    second = await other.get(path)
    assert second.status_code == 200
    assert second.json() == first.json()
    keys = await cache_keys(profile_api)
    assert len(keys) == 2
    assert sum(str(profile_api.user_id).encode() in key for key in keys) == 1
    assert sum(str(other.user_id).encode() in key for key in keys) == 1

    assert (await other.patch({"birth_date": "1990-01-01"})).status_code == 200
    assert (await other.get(path)).status_code == 200
    assert len(await cache_keys(profile_api)) == 3
    with patch.object(
        bio_engine, calculation(path), side_effect=AssertionError("unexpected compute")
    ):
        unchanged = await profile_api.get(path)
    assert unchanged.status_code == 200
    assert unchanged.json() == first.json()
    assert (await profile_api.get("/me")).json()["profile"]["birth_date"] == "2000-01-01"
    assert (await other.get("/me")).json()["profile"]["birth_date"] == "1990-01-01"


@pytest.mark.parametrize("path", BIO_PATHS)
@pytest.mark.parametrize("state", ["revoked", "unverified", "incomplete"])
async def test_cached_response_cannot_bypass_current_access_checks(
    profile_api: ProfileAPI, path: str, state: str
) -> None:
    await profile_api.complete()
    assert (await profile_api.get(path)).status_code == 200
    original_keys = await cache_keys(profile_api)
    async with profile_api.api.engine.begin() as connection:
        if state == "revoked":
            statement = update(AuthSession).where(AuthSession.user_id == profile_api.user_id)
            await connection.execute(statement.values(revoked_at=func.now()))
        elif state == "unverified":
            statement = update(User).where(User.id == profile_api.user_id)
            await connection.execute(statement.values(is_email_verified=False))
        else:
            statement = update(UserProfile).where(UserProfile.user_id == profile_api.user_id)
            await connection.execute(statement.values(onboarding_completed_at=None))
    with patch.object(
        profile_api.cache.backend, "get", side_effect=AssertionError("cache before guard")
    ):
        response = await profile_api.get(path)
    status, code = {
        "revoked": (401, "AUTHENTICATION_REQUIRED"),
        "unverified": (403, "EMAIL_NOT_VERIFIED"),
        "incomplete": (409, "ONBOARDING_REQUIRED"),
    }[state]
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"
    assert await cache_keys(profile_api) == original_keys


@pytest.mark.parametrize("path", BIO_PATHS)
async def test_api_works_during_redis_outage_and_resumes_caching(
    profile_api: ProfileAPI, path: str
) -> None:
    await profile_api.complete()
    unavailable: Redis = Redis.from_url(
        "redis://127.0.0.1:0", socket_timeout=0.05, socket_connect_timeout=0.05
    )
    profile_api.api.app.state.biorhythm_cache = BiorhythmCache(RedisBackend(unavailable))
    name = calculation(path)
    try:
        with patch.object(bio_engine, name, wraps=getattr(bio_engine, name)) as calculate:
            offline = await profile_api.get(path)
            assert offline.status_code == 200
            count = calculate.call_count
            assert count > 0
            assert not await cache_keys(profile_api)
            profile_api.api.app.state.biorhythm_cache = profile_api.cache
            recovered = await profile_api.get(path)
            assert recovered.status_code == 200
            assert recovered.json() == offline.json()
            assert calculate.call_count == count * 2
            cached = await profile_api.get(path)
            assert cached.status_code == 200
            assert cached.json() == offline.json()
            assert calculate.call_count == count * 2
            assert len(await cache_keys(profile_api)) == 1
    finally:
        profile_api.api.app.state.biorhythm_cache = profile_api.cache
        await unavailable.aclose()


async def test_forecast_cache_rolls_over_at_local_midnight(profile_api: ProfileAPI) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": "Asia/Yekaterinburg"})).status_code == 200
    before = datetime.fromisoformat("2026-11-08T18:59:59Z")
    app = profile_api.api.app
    app.dependency_overrides[get_clock] = lambda: FrozenClock(before)
    path = "/biorhythms/forecast?period=week"
    first = await profile_api.get(path)
    assert first.status_code == 200
    app.dependency_overrides[get_clock] = lambda: FrozenClock(before + timedelta(seconds=2))
    second = await profile_api.get(path)
    assert second.status_code == 200
    assert first.json()["start"] == "2026-11-08"
    assert second.json()["start"] == "2026-11-09"
    assert len(await cache_keys(profile_api)) == 2
