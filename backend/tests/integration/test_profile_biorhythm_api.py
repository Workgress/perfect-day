from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi_cache.backends.redis import RedisBackend
from httpx import Response
from redis.asyncio import Redis
from sqlalchemy import func, select, update

from app.core.security import decode_access_token
from app.core.time import FrozenClock
from app.modules.auth.models import AuthSession
from app.modules.biorhythm import engine as bio_engine
from app.modules.biorhythm.cache import BiorhythmCache
from app.modules.users.dependencies import get_clock, get_profile_changed_handler
from app.modules.users.events import ProfileChanged
from app.modules.users.models import User, UserProfile
from tests.integration.test_auth import AuthAPI
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url

pytestmark = pytest.mark.docker
NOW = datetime(2026, 11, 8, 10, tzinfo=UTC)
RANGE = "from=2026-11-01&to=2026-11-03"
BIO_PATHS = [
    "/biorhythms/now",
    f"/biorhythms?{RANGE}",
    f"/biorhythms/critical-days?{RANGE}",
    "/biorhythms/forecast?period=week",
]


@dataclass
class ProfileAPI:
    api: AuthAPI
    token: str
    user_id: UUID
    events: list[ProfileChanged]
    cache: BiorhythmCache

    async def get(self, path: str) -> Response:
        return await self.api.client.get(
            f"/api/v1{path}", headers={"Authorization": f"Bearer {self.token}"}
        )

    async def patch(self, body: dict[str, Any]) -> Response:
        return await self.api.client.patch(
            "/api/v1/me/profile", json=body, headers={"Authorization": f"Bearer {self.token}"}
        )

    async def complete(self) -> None:
        # Completion belongs to the future planner; prepare its persisted result here.
        response = await self.patch(
            {"birth_date": "2000-01-01", "birth_time": "12:00:00", "chronotype": "dove"}
        )
        assert response.status_code == 200
        async with self.api.engine.begin() as connection:
            await connection.execute(
                update(UserProfile)
                .where(UserProfile.user_id == self.user_id)
                .values(onboarding_completed_at=NOW)
            )


@pytest.fixture
async def profile_api(auth_api: AuthAPI) -> AsyncIterator[ProfileAPI]:
    assert (await auth_api.register()).status_code == 202
    verified = await auth_api.verify(auth_api.publisher.messages[-1][1])
    assert verified.status_code == 200
    token = verified.json()["access_token"]
    user_id = decode_access_token(token, auth_api.settings).sub
    events: list[ProfileChanged] = []

    async def changed(event: ProfileChanged) -> None:
        # A separate connection sees the write: notification really is after commit.
        async with auth_api.engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(UserProfile.user_id).where(UserProfile.user_id == event.user_id)
                )
                == event.user_id
            )
        events.append(event)

    cache = BiorhythmCache(RedisBackend(auth_api.redis), prefix=f"test:{uuid4()}")
    auth_api.app.state.biorhythm_cache = cache
    auth_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    auth_api.app.dependency_overrides[get_profile_changed_handler] = lambda: changed
    try:
        yield ProfileAPI(auth_api, token, user_id, events, cache)
    finally:
        keys = [key async for key in auth_api.redis.scan_iter(f"{cache.prefix}:bio:*")]
        if keys:
            await auth_api.redis.delete(*keys)


async def test_new_user_has_null_profile_and_can_save_steps(profile_api: ProfileAPI) -> None:
    response = await profile_api.get("/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    document = response.json()
    assert document == {
        "id": str(profile_api.user_id),
        "email": profile_api.api.email,
        "display_name": None,
        "profile": None,
        "onboarding": {"completed_at": None, "next_step": "birth_date"},
    }

    first = await profile_api.patch({"birth_date": "2000-02-29", "timezone": "Asia/Yekaterinburg"})
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["profile"]["birth_time"] is None
    assert first.json()["onboarding"]["next_step"] == "chronotype"
    second = await profile_api.patch({"chronotype": "owl", "sleep_time": "01:00:00"})
    assert second.status_code == 200
    profile = second.json()["profile"]
    assert profile["birth_date"] == "2000-02-29"
    assert profile["timezone"] == "Asia/Yekaterinburg"
    assert profile["sleep_time"] == "01:00:00"
    assert second.json()["onboarding"] == {"completed_at": None, "next_step": "first_tasks"}
    assert (await profile_api.get("/me")).json() == second.json()
    assert len(profile_api.events) == 2
    assert profile_api.events[-1].user_id == profile_api.user_id
    assert profile_api.events[-1].occurred_at == NOW
    assert "chronotype" in profile_api.events[-1].changed_fields
    assert "birth_date" not in profile_api.events[-1].changed_fields
    assert (await profile_api.get("/biorhythms/now")).status_code == 409


@pytest.mark.parametrize("path", BIO_PATHS)
async def test_biorhythms_require_completed_onboarding(profile_api: ProfileAPI, path: str) -> None:
    response = await profile_api.get(path)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ONBOARDING_REQUIRED"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/me", *BIO_PATHS, "/me/profile"])
async def test_routes_require_bearer_even_with_refresh_cookie(
    profile_api: ProfileAPI, path: str
) -> None:
    client = profile_api.api.client
    response = (
        await client.patch(f"/api/v1{path}", json={})
        if path == "/me/profile"
        else await client.get(f"/api/v1{path}")
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("state", ["unverified", "inactive", "revoked"])
async def test_existing_auth_checks_are_not_bypassed(profile_api: ProfileAPI, state: str) -> None:
    async with profile_api.api.engine.begin() as connection:
        if state == "revoked":
            await connection.execute(
                update(AuthSession)
                .where(AuthSession.user_id == profile_api.user_id)
                .values(revoked_at=func.now())
            )
        else:
            values = {"is_email_verified": False} if state == "unverified" else {"is_active": False}
            await connection.execute(
                update(User).where(User.id == profile_api.user_id).values(**values)
            )
    for path in ("/me", "/biorhythms/now"):
        response = await profile_api.get(path)
        assert response.status_code == (403 if state == "unverified" else 401)


async def test_profile_noop_and_failed_patch_do_not_emit_events(profile_api: ProfileAPI) -> None:
    assert (await profile_api.patch({"timezone": "UTC"})).status_code == 200
    count = len(profile_api.events)
    assert (await profile_api.patch({})).status_code == 200
    assert (await profile_api.patch({"timezone": "UTC"})).status_code == 200
    before = (await profile_api.get("/me")).json()
    failed = await profile_api.patch({"birth_date": "2000-01-01", "work_end": "07:00:00"})
    assert failed.status_code == 422
    assert failed.json()["error"]["details"]["fields"][0]["field"] == "body.work_end"
    assert (await profile_api.get("/me")).json() == before
    assert len(profile_api.events) == count


@pytest.mark.parametrize("field", ["birth_date", "chronotype"])
async def test_completed_profile_cannot_lose_required_fields(
    profile_api: ProfileAPI, field: str
) -> None:
    await profile_api.complete()
    before = (await profile_api.get("/me")).json()
    count = len(profile_api.events)
    failed = await profile_api.patch({field: None, "timezone": "Europe/Berlin"})
    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    assert (await profile_api.get("/me")).json() == before
    assert len(profile_api.events) == count
    valid = await profile_api.patch({"birth_time": None})
    assert valid.status_code == 200
    assert valid.json()["profile"]["birth_time"] is None
    assert valid.json()["onboarding"] == before["onboarding"]


@pytest.mark.parametrize("path", BIO_PATHS)
async def test_all_biorhythm_responses_are_serializable(profile_api: ProfileAPI, path: str) -> None:
    await profile_api.complete()
    response = await profile_api.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["algorithm_version"] == "1.0.0"
    assert body["timezone"] == "UTC"
    if path == "/biorhythms/now":
        assert body["at"] == "2026-11-08T10:00:00Z"
        assert body["date"] == "2026-11-08"
        assert set(body["cycles"]) == {"physical", "emotional", "intellectual"}
    elif "critical-days" in path:
        assert body["start"] == "2026-11-01" and body["end"] == "2026-11-03"
        assert all(1 <= day["level"] <= 3 for day in body["days"])
    else:
        assert len(body["points"]) == (7 if "forecast" in path else 3)
        assert body["step"] == "day"


async def test_snapshot_at_accepts_offset_and_matches_current_moment(
    profile_api: ProfileAPI,
) -> None:
    await profile_api.complete()
    now = await profile_api.get("/biorhythms/now")
    at = await profile_api.get("/biorhythms/now?at=2026-11-08T15:00:00%2B05:00")
    assert at.status_code == 200
    assert at.json() == now.json()


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ("/biorhythms/now?at=2026-11-08T10:00:00", "at"),
        ("/biorhythms/now?at=invalid", "at"),
        ("/biorhythms/now?at=1999-01-01T00:00:00Z", "at"),
        ("/biorhythms?to=2026-11-08", "from"),
        ("/biorhythms?from=2026-11-08", "to"),
        ("/biorhythms?from=2026-02-30&to=2026-03-01", "from"),
        ("/biorhythms?from=2026-11-01T00:00:00&to=2026-11-08", "from"),
        ("/biorhythms?from=2026-11-08&to=2026-11-01", "to"),
        ("/biorhythms?from=2026-01-01&to=2026-03-04", "to"),
        (f"/biorhythms?{RANGE}&step=minute", "step"),
        ("/biorhythms/forecast?period=year", "period"),
        ("/biorhythms/forecast", "period"),
        (f"/biorhythms/critical-days?{RANGE}&user_id=another", "user_id"),
    ],
)
async def test_invalid_query_uses_shared_error_contract(
    profile_api: ProfileAPI, path: str, field: str
) -> None:
    await profile_api.complete()
    response = await profile_api.get(path)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"][0]["field"] == f"query.{field}"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": "another"},
        {"birth_time": "12:00"},
        {"timezone": "Invalid/Zone"},
        {"birth_date": "2027-01-01"},
    ],
)
async def test_invalid_profile_does_not_create_a_row(
    profile_api: ProfileAPI, body: dict[str, Any]
) -> None:
    response = await profile_api.patch(body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (await profile_api.get("/me")).json()["profile"] is None
    assert not profile_api.events


async def test_profiles_and_calculations_are_isolated_between_tokens(
    profile_api: ProfileAPI,
) -> None:
    await profile_api.complete()
    first = (await profile_api.get("/biorhythms/now")).json()
    second_email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await profile_api.api.register(second_email)).status_code == 202
    verified = await profile_api.api.verify(profile_api.api.publisher.messages[-1][1])
    second_token = verified.json()["access_token"]
    other = ProfileAPI(profile_api.api, second_token, uuid4(), [], profile_api.cache)
    second_me = await other.get("/me")
    assert second_me.json()["email"] == second_email
    assert second_me.json()["profile"] is None
    assert (await other.get("/biorhythms/now")).status_code == 409
    assert (await other.patch({"birth_date": "1990-01-01"})).status_code == 200
    assert (await profile_api.get("/me")).json()["profile"]["birth_date"] == "2000-01-01"
    assert (await profile_api.get("/biorhythms/now")).json() == first


async def test_http_cache_hit_ttl_and_key_change_after_patch(profile_api: ProfileAPI) -> None:
    await profile_api.complete()
    with patch.object(bio_engine, "snapshot", wraps=bio_engine.snapshot) as calculate:
        first = await profile_api.get("/biorhythms/now")
        second = await profile_api.get("/biorhythms/now")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert calculate.call_count == 1
        keys = [
            key
            async for key in profile_api.api.redis.scan_iter(f"{profile_api.cache.prefix}:bio:*")
        ]
        assert len(keys) == 1
        assert 86390 <= await profile_api.api.redis.ttl(keys[0]) <= 86400
        assert (await profile_api.patch({"birth_date": "2000-01-02"})).status_code == 200
        # PATCH also calculates schedules now; measure the cache endpoint separately.
        calculate.reset_mock()
        changed = await profile_api.get("/biorhythms/now")
        assert changed.status_code == 200
        assert changed.json()["cycles"] != first.json()["cycles"]
        assert calculate.call_count == 1
    keys = [
        key async for key in profile_api.api.redis.scan_iter(f"{profile_api.cache.prefix}:bio:*")
    ]
    assert len(keys) == 2


async def test_http_calculates_when_redis_is_unreachable(profile_api: ProfileAPI) -> None:
    await profile_api.complete()
    expected = await profile_api.get("/biorhythms/now")
    unavailable: Redis = Redis.from_url(
        "redis://127.0.0.1:0", socket_connect_timeout=0.05, socket_timeout=0.05
    )
    profile_api.api.app.state.biorhythm_cache = BiorhythmCache(RedisBackend(unavailable))
    try:
        response = await profile_api.get("/biorhythms/now")
        assert response.status_code == 200
        assert response.json() == expected.json()
        assert response.headers["cache-control"] == "no-store"
    finally:
        await unavailable.aclose()
