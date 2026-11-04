import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Env, Settings, get_settings
from app.core.rate_limit import rate_limit_key
from app.core.security import decode_access_token, generate_token, hash_token, verify_password
from app.db.session import create_sessionmaker
from app.main import create_app
from app.modules.auth.delivery import VerificationPublishError, get_verification_publisher
from app.modules.auth.models import AuthSession, EmailToken, EmailTokenPurpose, RefreshToken
from app.modules.users.models import User, UserProfile
from tests.db.conftest import alembic_config as alembic_config
from tests.db.conftest import engine as engine
from tests.db.conftest import migrated_url as migrated_url

pytestmark = pytest.mark.docker


class CapturingPublisher:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.messages: list[tuple[str, str, datetime]] = []
        self.attempts: list[tuple[str, str, datetime]] = []
        self.fail = False

    async def publish(self, email: str, token: str, expires_at: datetime) -> None:
        async with self.engine.connect() as connection:
            stored = await connection.scalar(
                select(EmailToken.id).where(EmailToken.token_hash == hash_token(token))
            )
        assert stored is not None
        self.attempts.append((email, token, expires_at))
        if self.fail:
            raise VerificationPublishError("Test queue unavailable")
        self.messages.append((email, token, expires_at))


@dataclass
class AuthAPI:
    app: FastAPI
    client: AsyncClient
    engine: AsyncEngine
    settings: Settings
    redis: Redis
    publisher: CapturingPublisher
    email: str

    async def register(self, email: str | None = None, password: str = "Valid123") -> Response:
        return await self.client.post(
            "/api/v1/auth/register", json={"email": email or self.email, "password": password}
        )

    async def resend(self, email: str | None = None) -> Response:
        return await self.client.post(
            "/api/v1/auth/resend-verification", json={"email": email or self.email}
        )

    async def verify(self, token: str) -> Response:
        return await self.client.post("/api/v1/auth/verify-email", json={"token": token})


@pytest.fixture
async def auth_api(engine: AsyncEngine, redis_url: str) -> AsyncIterator[AuthAPI]:
    settings = Settings(
        _env_file=None,
        env=Env.TEST,
        jwt_secret=SecretStr("integration-auth-secret-with-at-least-32-bytes"),
        cors_origins=["http://localhost:5173"],
    )
    redis: Redis = Redis.from_url(f"{redis_url}/3", socket_timeout=2, socket_connect_timeout=2)
    publisher = CapturingPublisher(engine)
    app = create_app()
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_verification_publisher] = lambda: publisher
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Origin": "http://localhost:5173"},
        ) as client:
            yield AuthAPI(
                app,
                client,
                engine,
                settings,
                redis,
                publisher,
                f"{uuid4().hex}@auth-tests.example.com",
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(User).where(User.email.ilike("%@auth-tests.example.com"))
            )
        keys = [key async for key in redis.scan_iter("pd:auth:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


async def test_registration_confirmation_creates_one_session_and_hashed_refresh(
    auth_api: AuthAPI,
) -> None:
    registration = await auth_api.register()
    assert registration.status_code == 202
    assert "access_token" not in registration.json()
    assert "set-cookie" not in registration.headers
    assert len(auth_api.publisher.messages) == 1

    async with auth_api.engine.connect() as connection:
        user = (
            await connection.execute(select(User.__table__).where(User.email == auth_api.email))
        ).one()
        assert not user.is_email_verified
        assert await verify_password("Valid123", user.password_hash)
        assert await connection.scalar(select(func.count()).select_from(UserProfile)) == 0
        assert await connection.scalar(select(func.count()).select_from(AuthSession)) == 0

    token = auth_api.publisher.messages[0][1]
    response = await auth_api.verify(token)
    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type", "expires_in"}
    assert response.json()["expires_in"] == 900
    assert response.headers["cache-control"] == "no-store"
    cookie = SimpleCookie(response.headers["set-cookie"])["refresh_token"]
    assert cookie["httponly"]
    assert cookie["path"] == "/api/v1/auth"
    assert cookie["samesite"] == "strict"
    assert not cookie["domain"]
    claims = decode_access_token(response.json()["access_token"], auth_api.settings)

    async with auth_api.engine.connect() as connection:
        assert await connection.scalar(select(User.is_email_verified).where(User.id == user.id))
        device = (
            await connection.execute(
                select(AuthSession.__table__).where(AuthSession.id == claims.sid)
            )
        ).one()
        assert device.user_id == claims.sub == user.id
        assert device.expires_at - device.created_at == timedelta(days=30)
        assert device.ip == "127.0.0.1"
        assert await connection.scalar(select(RefreshToken.token_hash)) == hash_token(cookie.value)
        assert await connection.scalar(select(EmailToken.used_at)) is not None

    replay = await auth_api.verify(token)
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"
    assert "set-cookie" not in replay.headers


async def test_duplicate_registration_does_not_overwrite_account(auth_api: AuthAPI) -> None:
    first = await auth_api.register()
    async with auth_api.engine.connect() as connection:
        original = await connection.scalar(
            select(User.password_hash).where(User.email == auth_api.email)
        )
    second = await auth_api.register(auth_api.email.upper(), password="Different123")

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(auth_api.publisher.messages) == 1
    async with auth_api.engine.connect() as connection:
        assert (
            await connection.scalar(select(User.password_hash).where(User.email == auth_api.email))
            == original
        )


async def test_resend_before_cooldown_does_not_invalidate_sent_token(auth_api: AuthAPI) -> None:
    await auth_api.register()
    response = await auth_api.resend()

    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert len(auth_api.publisher.messages) == 1
    assert (await auth_api.verify(auth_api.publisher.messages[0][1])).status_code == 200


async def test_resend_invalidates_old_link(auth_api: AuthAPI) -> None:
    await auth_api.register()
    old = auth_api.publisher.messages[0][1]
    await auth_api.redis.delete(rate_limit_key("verification-email", auth_api.email))
    response = await auth_api.resend()

    assert response.status_code == 202
    assert len(auth_api.publisher.messages) == 2
    assert (await auth_api.verify(old)).status_code == 400
    assert (await auth_api.verify(auth_api.publisher.messages[1][1])).status_code == 200


@pytest.mark.parametrize("state", ["unknown", "verified", "inactive", "deleted"])
async def test_resend_response_does_not_reveal_account_state(auth_api: AuthAPI, state: str) -> None:
    if state != "unknown":
        async with auth_api.engine.begin() as connection:
            await connection.execute(
                User.__table__.insert().values(
                    email=auth_api.email,
                    password_hash="existing",
                    is_email_verified=state == "verified",
                    is_active=state != "inactive",
                    deleted_at=datetime.now(UTC) if state == "deleted" else None,
                )
            )
    first = await auth_api.resend()
    second = await auth_api.resend()

    assert first.status_code == 202
    assert second.status_code == 429
    assert auth_api.publisher.messages == []


@pytest.mark.parametrize("state", ["expired", "inactive", "deleted", "reset-purpose"])
async def test_verification_rejects_invalid_token_or_account(auth_api: AuthAPI, state: str) -> None:
    await auth_api.register()
    token = auth_api.publisher.messages[0][1]
    async with auth_api.engine.begin() as connection:
        if state == "expired":
            await connection.execute(
                update(EmailToken).values(
                    created_at=datetime.now(UTC) - timedelta(days=2),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        elif state == "reset-purpose":
            await connection.execute(
                update(EmailToken).values(purpose=EmailTokenPurpose.RESET_PASSWORD)
            )
        else:
            values = (
                {"is_active": False} if state == "inactive" else {"deleted_at": datetime.now(UTC)}
            )
            await connection.execute(
                update(User).where(User.email == auth_api.email).values(**values)
            )

    response = await auth_api.verify(token)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_EMAIL_TOKEN"
    assert "set-cookie" not in response.headers


async def test_unknown_verification_token_returns_safe_error(auth_api: AuthAPI) -> None:
    token = generate_token()
    response = await auth_api.verify(token)

    assert response.status_code == 400
    assert token not in response.text


async def test_missing_jwt_secret_does_not_consume_confirmation(auth_api: AuthAPI) -> None:
    await auth_api.register()
    token = auth_api.publisher.messages[0][1]
    secret = auth_api.settings.jwt_secret
    auth_api.settings.jwt_secret = None

    assert (await auth_api.verify(token)).status_code == 503
    async with auth_api.engine.connect() as connection:
        assert not await connection.scalar(
            select(User.is_email_verified).where(User.email == auth_api.email)
        )
        assert await connection.scalar(select(EmailToken.used_at)) is None

    auth_api.settings.jwt_secret = secret
    assert (await auth_api.verify(token)).status_code == 200


async def test_queue_failure_keeps_user_and_allows_immediate_resend(auth_api: AuthAPI) -> None:
    auth_api.publisher.fail = True
    response = await auth_api.register()

    assert response.status_code == 503
    assert await auth_api.redis.get(rate_limit_key("verification-email", auth_api.email)) is None
    old = auth_api.publisher.attempts[0][1]
    auth_api.publisher.fail = False
    assert (await auth_api.resend()).status_code == 202
    assert (await auth_api.verify(old)).status_code == 400
    assert (await auth_api.verify(auth_api.publisher.messages[0][1])).status_code == 200


async def test_concurrent_confirmation_creates_exactly_one_session(auth_api: AuthAPI) -> None:
    await auth_api.register()
    token = auth_api.publisher.messages[0][1]
    responses = await asyncio.gather(auth_api.verify(token), auth_api.verify(token))

    assert sorted(response.status_code for response in responses) == [200, 400]
    async with auth_api.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(AuthSession)) == 1
        assert await connection.scalar(select(func.count()).select_from(RefreshToken)) == 1


async def test_concurrent_registration_sends_one_email(auth_api: AuthAPI) -> None:
    responses = await asyncio.gather(auth_api.register(), auth_api.register())

    assert [response.status_code for response in responses] == [202, 202]
    assert len(auth_api.publisher.messages) == 1


async def test_concurrent_resends_send_one_replacement(auth_api: AuthAPI) -> None:
    await auth_api.register()
    await auth_api.redis.delete(rate_limit_key("verification-email", auth_api.email))
    responses = await asyncio.gather(auth_api.resend(), auth_api.resend())

    assert sorted(response.status_code for response in responses) == [202, 429]
    assert len(auth_api.publisher.messages) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "Valid123"},
        {"email": "user@auth-tests.example.com", "password": "short1"},
        {"email": "user@auth-tests.example.com", "password": "12345678"},
        {"email": "user@auth-tests.example.com", "password": "abcdefgh"},
    ],
)
async def test_registration_validation_is_safe(auth_api: AuthAPI, payload: dict[str, str]) -> None:
    response = await auth_api.client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422
    assert payload["password"] not in response.text
    assert auth_api.publisher.messages == []


async def test_missing_origin_denies_registration(auth_api: AuthAPI) -> None:
    auth_api.client.headers.pop("Origin")
    response = await auth_api.register()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_ORIGIN_DENIED"
    assert auth_api.publisher.messages == []


async def test_redis_failure_denies_registration_before_creating_user(
    auth_api: AuthAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_api.redis, "eval", AsyncMock(side_effect=RedisConnectionError("private-host"))
    )

    response = await auth_api.register()

    assert response.status_code == 503
    assert "private-host" not in response.text
    assert auth_api.publisher.attempts == []
    async with auth_api.engine.connect() as connection:
        assert await connection.scalar(select(User.id).where(User.email == auth_api.email)) is None


async def test_registration_limit_blocks_eleventh_request(auth_api: AuthAPI) -> None:
    responses = [
        await auth_api.register(f"{uuid4().hex}@auth-tests.example.com") for _ in range(11)
    ]

    assert [response.status_code for response in responses] == [202] * 10 + [429]
    assert len(auth_api.publisher.messages) == 10
    assert 1 <= int(responses[-1].headers["retry-after"]) <= 3600


async def test_verification_limit_blocks_thirty_first_request(auth_api: AuthAPI) -> None:
    responses = [await auth_api.verify("invalid-token") for _ in range(31)]

    assert [response.status_code for response in responses] == [400] * 30 + [429]
