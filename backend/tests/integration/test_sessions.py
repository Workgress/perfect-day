import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from typing import Annotated
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient, Response
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token, get_current_user, hash_token
from app.db.session import get_session
from app.modules.auth.models import AuthSession, RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import User, UserProfile
from tests.integration.test_auth import AuthAPI
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url

pytestmark = pytest.mark.docker


@dataclass(frozen=True)
class Device:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    id: UUID
    user_id: UUID


def device_from(response: Response, api: AuthAPI) -> Device:
    assert response.status_code == 200
    access = response.json()["access_token"]
    claims = decode_access_token(access, api.settings)
    return Device(
        access,
        SimpleCookie(response.headers["set-cookie"])["refresh_token"].value,
        claims.sid,
        claims.sub,
    )


def bearer(device: Device) -> dict[str, str]:
    return {"Authorization": f"Bearer {device.access}"}


def cookie(token: str | None) -> dict[str, str]:
    return {"Cookie": f"refresh_token={token}" if token else ""}


@dataclass
class SessionsAPI:
    api: AuthAPI
    initial: Device

    async def login(self, email: str | None = None, password: str = "Valid123") -> Response:
        return await self.api.client.post(
            "/api/v1/auth/login",
            data={"username": email or self.api.email, "password": password},
        )

    async def new_device(self) -> Device:
        return device_from(await self.login(), self.api)

    async def refresh(self, token: str | None) -> Response:
        return await self.api.client.post("/api/v1/auth/refresh", headers=cookie(token))

    async def logout(self, token: str | None) -> Response:
        return await self.api.client.post("/api/v1/auth/logout", headers=cookie(token))

    async def protected(self, device: Device) -> Response:
        return await self.api.client.get("/test/protected", headers=bearer(device))


@pytest.fixture
async def sessions_api(auth_api: AuthAPI) -> SessionsAPI:
    @auth_api.app.get("/test/protected")
    async def protected(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str]:
        return {"id": str(user.id)}

    @auth_api.app.get("/test/transaction")
    async def transaction(
        user: Annotated[User, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, int]:
        async with session.begin():
            count = await session.scalar(
                select(func.count()).select_from(UserProfile).where(UserProfile.user_id == user.id)
            )
        return {"profiles": count or 0}

    assert (await auth_api.register()).status_code == 202
    response = await auth_api.verify(auth_api.publisher.messages[-1][1])
    return SessionsAPI(auth_api, device_from(response, auth_api))


async def test_login_creates_separate_device_without_profile(sessions_api: SessionsAPI) -> None:
    response = await sessions_api.login(email=sessions_api.api.email.upper())
    device = device_from(response, sessions_api.api)

    assert device.id != sessions_api.initial.id
    assert device.user_id == sessions_api.initial.user_id
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["expires_in"] == 900
    assert (await sessions_api.protected(device)).json() == {"id": str(device.user_id)}
    transaction = await sessions_api.api.client.get("/test/transaction", headers=bearer(device))
    assert transaction.status_code == 200
    assert transaction.json() == {"profiles": 0}


@pytest.mark.parametrize("state", ["wrong-password", "unknown-email", "invalid-email", "oversized"])
async def test_login_uses_same_error_for_invalid_credentials(
    sessions_api: SessionsAPI, state: str
) -> None:
    email = sessions_api.api.email
    password = "Wrong123"
    if state == "unknown-email":
        email, password = "unknown@auth-tests.example.com", "Valid123"
    elif state == "invalid-email":
        email, password = "not-an-email", "Valid123"
    elif state == "oversized":
        password = "a1" + "x" * 127
    response = await sessions_api.login(email, password)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.headers["www-authenticate"] == "Bearer"
    assert "set-cookie" not in response.headers
    assert password not in response.text


async def test_login_requires_oauth2_form(sessions_api: SessionsAPI) -> None:
    response = await sessions_api.api.client.post(
        "/api/v1/auth/login", json={"username": sessions_api.api.email, "password": "Valid123"}
    )

    assert response.status_code == 422
    assert "Valid123" not in response.text


@pytest.mark.parametrize("state", ["unverified", "inactive", "deleted"])
async def test_login_rejects_unavailable_accounts(sessions_api: SessionsAPI, state: str) -> None:
    values = {
        "unverified": {"is_email_verified": False},
        "inactive": {"is_active": False},
        "deleted": {"deleted_at": datetime.now(UTC)},
    }[state]
    async with sessions_api.api.engine.begin() as connection:
        await connection.execute(
            update(User).where(User.id == sessions_api.initial.user_id).values(**values)
        )
    response = await sessions_api.login()

    assert response.status_code == (403 if state == "unverified" else 401)
    assert "set-cookie" not in response.headers
    async with sessions_api.api.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(AuthSession)) == 1


async def test_login_rate_limit_normalizes_email_and_ignores_forwarded_ip(
    sessions_api: SessionsAPI,
) -> None:
    responses = [
        await sessions_api.login(sessions_api.api.email.upper(), password="Wrong123")
        for _ in range(5)
    ]
    blocked = await sessions_api.api.client.post(
        "/api/v1/auth/login",
        data={"username": f" {sessions_api.api.email} ", "password": "Wrong123"},
        headers={"X-Forwarded-For": "192.0.2.100"},
    )

    assert [response.status_code for response in responses] == [401] * 5
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    display_name = await sessions_api.login(f"Name <{sessions_api.api.email}>", "Wrong123")
    assert display_name.status_code == 429
    assert (
        await sessions_api.login("another@auth-tests.example.com", "Wrong123")
    ).status_code == 401
    async with AsyncClient(
        transport=ASGITransport(app=sessions_api.api.app, client=("192.0.2.101", 1234)),
        base_url="http://test",
        headers={"Origin": "http://localhost:5173"},
    ) as client:
        assert (
            await client.post(
                "/api/v1/auth/login",
                data={"username": sessions_api.api.email, "password": "Wrong123"},
            )
        ).status_code == 401


async def test_refresh_rotates_token_and_preserves_absolute_session_expiration(
    sessions_api: SessionsAPI,
) -> None:
    device = sessions_api.initial
    async with sessions_api.api.engine.connect() as connection:
        original_expiration = await connection.scalar(
            select(AuthSession.expires_at).where(AuthSession.id == device.id)
        )
    tokens = [device.refresh]
    for _ in range(3):
        response = await sessions_api.refresh(tokens[-1])
        rotated = device_from(response, sessions_api.api)
        assert rotated.id == device.id
        assert rotated.refresh not in tokens
        assert set(response.json()) == {"access_token", "token_type", "expires_in"}
        tokens.append(rotated.refresh)

    async with sessions_api.api.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(AuthSession.expires_at).where(AuthSession.id == device.id)
            )
            == original_expiration
        )
        rows = (await connection.execute(select(RefreshToken.__table__))).all()
        assert len(rows) == 4
        assert len([row for row in rows if row.used_at is None]) == 1
        assert {row.token_hash for row in rows} == {hash_token(token) for token in tokens}
        assert all(row.expires_at == original_expiration for row in rows)
        assert len([row for row in rows if row.replaced_by_id is not None]) == 3


async def test_refresh_does_not_require_valid_access(sessions_api: SessionsAPI) -> None:
    expired_access = create_access_token(
        sessions_api.initial.user_id,
        sessions_api.initial.id,
        sessions_api.api.settings,
        now=datetime.now(UTC) - timedelta(days=1),
    )
    response = await sessions_api.api.client.post(
        "/api/v1/auth/refresh",
        headers={
            **cookie(sessions_api.initial.refresh),
            "Authorization": f"Bearer {expired_access}",
        },
    )

    assert response.status_code == 200


async def test_refresh_replay_commits_revocation_and_spares_other_device(
    sessions_api: SessionsAPI,
) -> None:
    other = await sessions_api.new_device()
    rotated = device_from(
        await sessions_api.refresh(sessions_api.initial.refresh), sessions_api.api
    )
    replay = await sessions_api.refresh(sessions_api.initial.refresh)

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"
    assert SimpleCookie(replay.headers["set-cookie"])["refresh_token"]["max-age"] == "0"
    async with sessions_api.api.engine.connect() as connection:
        assert (
            await connection.scalar(
                select(AuthSession.revoked_at).where(AuthSession.id == sessions_api.initial.id)
            )
            is not None
        )
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401
    assert (await sessions_api.protected(rotated)).status_code == 401
    assert (await sessions_api.refresh(rotated.refresh)).status_code == 401
    assert (await sessions_api.protected(other)).status_code == 200


async def test_concurrent_refresh_rejects_replay_and_revokes_device(
    sessions_api: SessionsAPI,
) -> None:
    responses = await asyncio.gather(
        sessions_api.refresh(sessions_api.initial.refresh),
        sessions_api.refresh(sessions_api.initial.refresh),
    )

    assert sorted(response.status_code for response in responses) == [200, 401]
    successful = next(response for response in responses if response.status_code == 200)
    rotated = device_from(successful, sessions_api.api)
    assert (await sessions_api.protected(rotated)).status_code == 401
    async with sessions_api.api.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(RefreshToken)) == 2


@pytest.mark.parametrize("token", [None, "unknown-token", "x" * 257])
async def test_invalid_refresh_clears_cookie(sessions_api: SessionsAPI, token: str | None) -> None:
    response = await sessions_api.refresh(token)

    assert response.status_code == 401
    cleared = SimpleCookie(response.headers["set-cookie"])["refresh_token"]
    assert cleared["max-age"] == "0"
    assert cleared["httponly"]
    assert cleared["path"] == "/api/v1/auth"
    assert cleared["samesite"] == "strict"
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


async def test_refresh_does_not_accept_token_in_json_or_access_as_refresh(
    sessions_api: SessionsAPI,
) -> None:
    response = await sessions_api.api.client.post(
        "/api/v1/auth/refresh",
        headers=cookie(None),
        json={"refresh_token": sessions_api.initial.refresh},
    )

    assert response.status_code == 401
    assert (await sessions_api.refresh(sessions_api.initial.access)).status_code == 401
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


@pytest.mark.parametrize(
    "state", ["token-expired", "session-expired", "inactive", "deleted", "unverified"]
)
async def test_refresh_rejects_invalid_token_session_or_user(
    sessions_api: SessionsAPI, state: str
) -> None:
    now = datetime.now(UTC)
    async with sessions_api.api.engine.begin() as connection:
        if state == "token-expired":
            await connection.execute(
                update(RefreshToken).values(
                    created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
                )
            )
        elif state == "session-expired":
            await connection.execute(
                update(AuthSession).values(
                    created_at=now - timedelta(days=2),
                    last_used_at=now - timedelta(days=1),
                    expires_at=now - timedelta(days=1),
                )
            )
        else:
            values = {
                "inactive": {"is_active": False},
                "deleted": {"deleted_at": now},
                "unverified": {"is_email_verified": False},
            }[state]
            await connection.execute(
                update(User).where(User.id == sessions_api.initial.user_id).values(**values)
            )

    response = await sessions_api.refresh(sessions_api.initial.refresh)

    assert response.status_code == 401
    async with sessions_api.api.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(RefreshToken)) == 1


async def test_logout_revokes_access_and_preserves_other_device(sessions_api: SessionsAPI) -> None:
    other = await sessions_api.new_device()
    response = await sessions_api.logout(sessions_api.initial.refresh)

    assert response.status_code == 204
    assert not response.content
    assert SimpleCookie(response.headers["set-cookie"])["refresh_token"]["max-age"] == "0"
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401
    assert (await sessions_api.protected(other)).status_code == 200
    assert (await sessions_api.refresh(sessions_api.initial.refresh)).status_code == 401


@pytest.mark.parametrize("token", [None, "unknown-token"])
async def test_logout_is_idempotent_for_missing_or_unknown_cookie(
    sessions_api: SessionsAPI, token: str | None
) -> None:
    assert (await sessions_api.logout(token)).status_code == 204
    assert (await sessions_api.logout(token)).status_code == 204


async def test_logout_with_rotated_token_still_revokes_device(sessions_api: SessionsAPI) -> None:
    rotated = device_from(
        await sessions_api.refresh(sessions_api.initial.refresh), sessions_api.api
    )

    assert (await sessions_api.logout(sessions_api.initial.refresh)).status_code == 204
    assert (await sessions_api.protected(rotated)).status_code == 401


async def test_logout_all_revokes_only_authenticated_users_devices(
    sessions_api: SessionsAPI,
) -> None:
    other = await sessions_api.new_device()
    foreign_email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await sessions_api.api.register(foreign_email)).status_code == 202
    foreign = device_from(
        await sessions_api.api.verify(sessions_api.api.publisher.messages[-1][1]), sessions_api.api
    )
    sessions_api.api.client.headers.pop("Origin")
    response = await sessions_api.api.client.post(
        "/api/v1/auth/logout-all", headers=bearer(sessions_api.initial)
    )

    assert response.status_code == 204
    assert not response.content
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401
    assert (await sessions_api.protected(other)).status_code == 401
    assert (await sessions_api.protected(foreign)).status_code == 200


async def test_active_sessions_have_current_marker_and_follow_refresh_order(
    sessions_api: SessionsAPI,
) -> None:
    other = await sessions_api.new_device()
    await sessions_api.refresh(sessions_api.initial.refresh)
    sessions_api.api.client.headers.pop("Origin")
    response = await sessions_api.api.client.get(
        "/api/v1/auth/sessions", headers=bearer(sessions_api.initial)
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(sessions_api.initial.id), str(other.id)]
    assert [item["is_current"] for item in items] == [True, False]
    assert set(items[0]) == {
        "id",
        "created_at",
        "expires_at",
        "last_used_at",
        "ip",
        "user_agent",
        "is_current",
    }
    assert sessions_api.initial.refresh not in response.text


async def test_sessions_list_excludes_revoked_and_expired_devices(
    sessions_api: SessionsAPI,
) -> None:
    revoked = await sessions_api.new_device()
    expired = await sessions_api.new_device()
    await sessions_api.logout(revoked.refresh)
    now = datetime.now(UTC)
    async with sessions_api.api.engine.begin() as connection:
        await connection.execute(
            update(AuthSession)
            .where(AuthSession.id == expired.id)
            .values(
                created_at=now - timedelta(days=2),
                last_used_at=now - timedelta(days=1),
                expires_at=now - timedelta(days=1),
            )
        )
    response = await sessions_api.api.client.get(
        "/api/v1/auth/sessions", headers=bearer(sessions_api.initial)
    )

    assert [item["id"] for item in response.json()["items"]] == [str(sessions_api.initial.id)]


async def test_revoking_other_device_is_idempotent_and_keeps_current_cookie(
    sessions_api: SessionsAPI,
) -> None:
    other = await sessions_api.new_device()
    for _ in range(2):
        response = await sessions_api.api.client.delete(
            f"/api/v1/auth/sessions/{other.id}", headers=bearer(sessions_api.initial)
        )
        assert response.status_code == 204
        assert "set-cookie" not in response.headers
    assert (await sessions_api.protected(other)).status_code == 401
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


async def test_revoking_current_device_clears_cookie(sessions_api: SessionsAPI) -> None:
    response = await sessions_api.api.client.delete(
        f"/api/v1/auth/sessions/{sessions_api.initial.id}", headers=bearer(sessions_api.initial)
    )

    assert response.status_code == 204
    assert SimpleCookie(response.headers["set-cookie"])["refresh_token"]["max-age"] == "0"
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401


async def test_foreign_and_nonexistent_session_ids_return_same_error(
    sessions_api: SessionsAPI,
) -> None:
    foreign_email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await sessions_api.api.register(foreign_email)).status_code == 202
    foreign = device_from(
        await sessions_api.api.verify(sessions_api.api.publisher.messages[-1][1]), sessions_api.api
    )
    responses = [
        await sessions_api.api.client.delete(
            f"/api/v1/auth/sessions/{session_id}", headers=bearer(sessions_api.initial)
        )
        for session_id in (foreign.id, uuid4())
    ]

    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert (await sessions_api.protected(foreign)).status_code == 200


@pytest.mark.parametrize("authorization", [None, "Basic invalid", "Bearer malformed"])
async def test_protected_routes_do_not_accept_refresh_cookie_as_authentication(
    sessions_api: SessionsAPI, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = await sessions_api.api.client.get("/api/v1/auth/sessions", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_access_claims_must_reference_matching_user_and_session(
    sessions_api: SessionsAPI,
) -> None:
    mismatched = create_access_token(uuid4(), sessions_api.initial.id, sessions_api.api.settings)
    response = await sessions_api.api.client.get(
        "/test/protected", headers={"Authorization": f"Bearer {mismatched}"}
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "state", ["expired-access", "unverified", "inactive", "deleted", "session-missing"]
)
async def test_current_user_checks_live_database_state(
    sessions_api: SessionsAPI, state: str
) -> None:
    access = sessions_api.initial.access
    if state == "expired-access":
        access = create_access_token(
            sessions_api.initial.user_id,
            sessions_api.initial.id,
            sessions_api.api.settings,
            now=datetime.now(UTC) - timedelta(days=1),
        )
    else:
        async with sessions_api.api.engine.begin() as connection:
            if state == "session-missing":
                await connection.execute(
                    delete(AuthSession).where(AuthSession.id == sessions_api.initial.id)
                )
            else:
                values = {
                    "unverified": {"is_email_verified": False},
                    "inactive": {"is_active": False},
                    "deleted": {"deleted_at": datetime.now(UTC)},
                }[state]
                await connection.execute(
                    update(User).where(User.id == sessions_api.initial.user_id).values(**values)
                )
    response = await sessions_api.api.client.get(
        "/test/protected", headers={"Authorization": f"Bearer {access}"}
    )

    assert response.status_code == (403 if state == "unverified" else 401)


async def test_mutating_auth_operation_rechecks_cached_user_under_lock(
    sessions_api: SessionsAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = AuthRepository.lock_user

    async def disable_before_lock(repository: AuthRepository, user_id: UUID) -> User | None:
        async with sessions_api.api.engine.begin() as connection:
            await connection.execute(update(User).where(User.id == user_id).values(is_active=False))
        return await original(repository, user_id)

    monkeypatch.setattr(AuthRepository, "lock_user", disable_before_lock)
    response = await sessions_api.api.client.get(
        "/api/v1/auth/sessions", headers=bearer(sessions_api.initial)
    )

    assert response.status_code == 401


@pytest.mark.parametrize("operation", ["logout", "logout-all", "delete"])
async def test_concurrent_refresh_and_revocation_do_not_leave_active_target(
    sessions_api: SessionsAPI, operation: str
) -> None:
    target = await sessions_api.new_device() if operation == "delete" else sessions_api.initial
    if operation == "logout":
        revoke = sessions_api.logout(target.refresh)
    elif operation == "logout-all":
        revoke = sessions_api.api.client.post(
            "/api/v1/auth/logout-all", headers=bearer(sessions_api.initial)
        )
    else:
        revoke = sessions_api.api.client.delete(
            f"/api/v1/auth/sessions/{target.id}", headers=bearer(sessions_api.initial)
        )
    refresh, revocation = await asyncio.gather(sessions_api.refresh(target.refresh), revoke)

    assert revocation.status_code == 204
    assert refresh.status_code in (200, 401)
    assert (await sessions_api.protected(target)).status_code == 401
    if operation == "delete":
        assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


@pytest.mark.parametrize("path", ["login", "refresh", "logout"])
async def test_cookie_auth_routes_require_trusted_source(
    sessions_api: SessionsAPI, path: str
) -> None:
    sessions_api.api.client.headers.pop("Origin")
    response = await sessions_api.api.client.post(
        f"/api/v1/auth/{path}", data={"username": sessions_api.api.email, "password": "Valid123"}
    )

    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


async def test_database_auth_and_global_logout_work_without_redis(
    sessions_api: SessionsAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sessions_api.api.redis, "eval", AsyncMock(side_effect=RedisConnectionError("private-host"))
    )

    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200
    assert (await sessions_api.login()).status_code == 503
    response = await sessions_api.api.client.post(
        "/api/v1/auth/logout-all", headers=bearer(sessions_api.initial)
    )
    assert response.status_code == 204
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401
