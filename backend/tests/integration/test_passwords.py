import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.core.rate_limit import rate_limit_key
from app.core.security import hash_token, verify_password
from app.modules.auth.models import AuthSession, EmailToken, EmailTokenPurpose
from app.modules.users.models import User
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url
from tests.integration.test_sessions import SessionsAPI, bearer, cookie, device_from
from tests.integration.test_sessions import sessions_api as sessions_api

pytestmark = pytest.mark.docker
PREFIX = "/api/v1/auth/password"
NEW_PASSWORD = "Changed456"


async def request_reset(api: SessionsAPI) -> str:
    response = await api.api.client.post(f"{PREFIX}/forgot", json={"email": api.api.email})
    assert response.status_code == 202
    return api.api.publisher.messages[-1][1]


async def test_reset_changes_password_revokes_all_devices_and_is_single_use(
    sessions_api: SessionsAPI,
) -> None:
    api = sessions_api.api
    second = await sessions_api.new_device()
    token = await request_reset(sessions_api)
    async with api.engine.connect() as connection:
        stored = (
            await connection.execute(
                select(EmailToken.__table__).where(EmailToken.token_hash == hash_token(token))
            )
        ).one()
        assert stored.purpose == EmailTokenPurpose.RESET_PASSWORD
        assert stored.expires_at - stored.created_at == timedelta(minutes=60)
        assert token not in stored.token_hash
    body = {"token": token, "new_password": NEW_PASSWORD}
    response = await api.client.post(f"{PREFIX}/reset", json=body)
    assert response.status_code == 204
    assert response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    for device in (sessions_api.initial, second):
        assert (await sessions_api.protected(device)).status_code == 401
        assert (await sessions_api.refresh(device.refresh)).status_code == 401
    assert (await api.client.post(f"{PREFIX}/reset", json=body)).status_code == 400
    assert (await sessions_api.login()).status_code == 401
    assert (await sessions_api.login(password=NEW_PASSWORD)).status_code == 200


@pytest.mark.parametrize("state", ["unknown", "unverified", "inactive", "deleted"])
async def test_forgot_does_not_disclose_or_send_for_unavailable_accounts(
    sessions_api: SessionsAPI, state: str
) -> None:
    api = sessions_api.api
    email = api.email
    if state == "unknown":
        email = f"{uuid4().hex}@auth-tests.example.com"
    else:
        values = {
            "unverified": {"is_email_verified": False},
            "inactive": {"is_active": False},
            "deleted": {"deleted_at": datetime.now(UTC)},
        }[state]
        async with api.engine.begin() as connection:
            await connection.execute(
                update(User).where(User.id == sessions_api.initial.user_id).values(**values)
            )
    before = len(api.publisher.messages)
    response = await api.client.post(f"{PREFIX}/forgot", json={"email": email})
    assert response.status_code == 202
    assert response.json() == {
        "message": "Если действие доступно для указанного адреса, письмо будет отправлено"
    }
    assert "set-cookie" not in response.headers
    assert len(api.publisher.messages) == before


async def test_forgot_invalidates_previous_reset_but_not_verification(
    sessions_api: SessionsAPI,
) -> None:
    api = sessions_api.api
    first = await request_reset(sessions_api)
    second = await request_reset(sessions_api)
    assert first != second
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200
    assert (
        await api.client.post(
            f"{PREFIX}/reset", json={"token": first, "new_password": NEW_PASSWORD}
        )
    ).status_code == 400
    assert (
        await api.client.post(
            f"{PREFIX}/reset", json={"token": second, "new_password": NEW_PASSWORD}
        )
    ).status_code == 204


@pytest.mark.parametrize(
    "state", ["unknown", "expired", "used", "verification", "inactive", "deleted", "unverified"]
)
async def test_reset_rejects_invalid_token_or_user_without_changing_password(
    sessions_api: SessionsAPI, state: str
) -> None:
    api = sessions_api.api
    token = await request_reset(sessions_api)
    async with api.engine.begin() as connection:
        if state in ("expired", "used"):
            values = (
                {
                    "created_at": datetime.now(UTC) - timedelta(hours=2),
                    "expires_at": datetime.now(UTC) - timedelta(hours=1),
                }
                if state == "expired"
                else {"used_at": datetime.now(UTC)}
            )
            await connection.execute(
                update(EmailToken)
                .where(EmailToken.token_hash == hash_token(token))
                .values(**values)
            )
        elif state in ("inactive", "deleted", "unverified"):
            values = {
                "inactive": {"is_active": False},
                "deleted": {"deleted_at": datetime.now(UTC)},
                "unverified": {"is_email_verified": False},
            }[state]
            await connection.execute(
                update(User).where(User.id == sessions_api.initial.user_id).values(**values)
            )
    if state == "unknown":
        token = "unknown-token"
    elif state == "verification":
        token = api.publisher.messages[0][1]
    response = await api.client.post(
        f"{PREFIX}/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"
    async with api.engine.connect() as connection:
        password_hash = await connection.scalar(
            select(User.password_hash).where(User.id == sessions_api.initial.user_id)
        )
        assert await verify_password("Valid123", password_hash)
        assert (
            await connection.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_not(None))
            )
            == 0
        )


async def test_change_revokes_devices_and_outstanding_reset_links(
    sessions_api: SessionsAPI,
) -> None:
    api = sessions_api.api
    second = await sessions_api.new_device()
    token = await request_reset(sessions_api)
    response = await api.client.post(
        f"{PREFIX}/change",
        headers={**bearer(sessions_api.initial), "Origin": "http://untrusted.example"},
        json={"old_password": "Valid123", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    for device in (sessions_api.initial, second):
        assert (await sessions_api.protected(device)).status_code == 401
        assert (await sessions_api.refresh(device.refresh)).status_code == 401
    assert (
        await api.client.post(
            f"{PREFIX}/reset", json={"token": token, "new_password": "Another789"}
        )
    ).status_code == 400
    assert (await sessions_api.login()).status_code == 401
    assert (await sessions_api.login(password=NEW_PASSWORD)).status_code == 200


async def test_change_wrong_password_does_not_mutate_and_is_rate_limited(
    sessions_api: SessionsAPI,
) -> None:
    api = sessions_api.api
    for _ in range(5):
        response = await api.client.post(
            f"{PREFIX}/change",
            headers=bearer(sessions_api.initial),
            json={"old_password": "Wrong123", "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    limited = await api.client.post(
        f"{PREFIX}/change",
        headers=bearer(sessions_api.initial),
        json={"old_password": "Valid123", "new_password": NEW_PASSWORD},
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200


@pytest.mark.parametrize("mode", ["reset", "change"])
async def test_parallel_password_updates_only_succeed_once(
    sessions_api: SessionsAPI, mode: str
) -> None:
    api = sessions_api.api
    token = await request_reset(sessions_api)
    body = {"new_password": NEW_PASSWORD}
    body.update({"token": token} if mode == "reset" else {"old_password": "Valid123"})
    responses = await asyncio.gather(
        *[
            api.client.post(f"{PREFIX}/{mode}", json=body, headers=bearer(sessions_api.initial))
            for _ in range(2)
        ]
    )
    assert sorted(response.status_code for response in responses) == (
        [204, 400] if mode == "reset" else [204, 401]
    )


@pytest.mark.parametrize("mode", ["reset", "change"])
async def test_password_update_racing_refresh_leaves_old_session_revoked(
    sessions_api: SessionsAPI, mode: str
) -> None:
    api = sessions_api.api
    token = await request_reset(sessions_api)
    body = {"new_password": NEW_PASSWORD}
    body.update({"token": token} if mode == "reset" else {"old_password": "Valid123"})
    changed, refreshed = await asyncio.gather(
        api.client.post(f"{PREFIX}/{mode}", json=body, headers=bearer(sessions_api.initial)),
        sessions_api.refresh(sessions_api.initial.refresh),
    )
    assert changed.status_code == 204
    assert refreshed.status_code in (200, 401)
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 401
    if refreshed.status_code == 200:
        rotated = device_from(refreshed, api)
        assert (await sessions_api.refresh(rotated.refresh)).status_code == 401


@pytest.mark.parametrize("scope", ["ip", "email"])
async def test_forgot_limits_ip_and_normalized_email_independently(
    sessions_api: SessionsAPI, scope: str
) -> None:
    api = sessions_api.api
    for index in range(4):
        ip = f"198.51.100.{index}" if scope == "email" else "198.51.100.99"
        email = api.email if scope == "email" else f"{index}@auth-tests.example.com"
        async with AsyncClient(
            transport=ASGITransport(app=api.app, client=(ip, 1234)),
            base_url="http://test",
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            response = await client.post(
                f"{PREFIX}/forgot", json={"email": f"Name <{email.upper()}>"}
            )
        assert response.status_code == (202 if index < 3 else 429)
    assert int(response.headers["retry-after"]) > 0
    identity = api.email if scope == "email" else "198.51.100.99"
    key = rate_limit_key(f"password-forgot-{scope}", identity)
    assert await api.redis.ttl(key) > 0


async def test_reset_limits_attempts_and_queue_failure_can_be_retried(
    sessions_api: SessionsAPI,
) -> None:
    api = sessions_api.api
    api.publisher.fail = True
    failed = await api.client.post(f"{PREFIX}/forgot", json={"email": api.email})
    assert failed.status_code == 503
    api.publisher.fail = False
    await request_reset(sessions_api)
    for index in range(31):
        response = await api.client.post(
            f"{PREFIX}/reset", json={"token": "invalid", "new_password": NEW_PASSWORD}
        )
        assert response.status_code == (400 if index < 30 else 429)


@pytest.mark.parametrize("mode", ["forgot", "reset", "change"])
async def test_password_routes_require_correct_authorization(
    sessions_api: SessionsAPI, mode: str
) -> None:
    api = sessions_api.api
    body = {
        "forgot": {"email": api.email},
        "reset": {"token": "invalid", "new_password": NEW_PASSWORD},
        "change": {"old_password": "Valid123", "new_password": NEW_PASSWORD},
    }[mode]
    response = await api.client.post(
        f"{PREFIX}/{mode}",
        headers={"Origin": "http://untrusted.example", **cookie(sessions_api.initial.refresh)},
        json=body,
    )
    assert response.status_code == (401 if mode == "change" else 403)


@pytest.mark.parametrize("mode", ["reset", "change"])
@pytest.mark.parametrize("password", ["short1", "abcdefgh", "12345678", "a1" + "x" * 127])
async def test_password_policy_rejects_without_exposing_secrets(
    sessions_api: SessionsAPI, mode: str, password: str
) -> None:
    token = await request_reset(sessions_api)
    body = {"new_password": password}
    body.update({"token": token} if mode == "reset" else {"old_password": "Valid123"})
    response = await sessions_api.api.client.post(
        f"{PREFIX}/{mode}", json=body, headers=bearer(sessions_api.initial)
    )
    assert response.status_code == 422
    assert password not in response.text
    assert token not in response.text
    assert "Valid123" not in response.text
    assert (await sessions_api.protected(sessions_api.initial)).status_code == 200
