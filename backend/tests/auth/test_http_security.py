from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response
from pydantic import SecretStr
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Env, Settings
from app.core.csrf import require_trusted_origin
from app.core.errors import AppError
from app.core.rate_limit import AuthRateLimiter, rate_limit_key
from app.modules.auth.cookies import set_refresh_cookie


def local_settings() -> Settings:
    return Settings(_env_file=None, env=Env.TEST)


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://localhost:5173"},
        {"referer": "http://localhost:5173/verify-email"},
    ],
)
def test_csrf_accepts_trusted_origin_or_referer(headers: dict[str, str]) -> None:
    request = Request(
        {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    )

    require_trusted_origin(request, local_settings())


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": "null"},
        {"origin": "http://localhost:5173.evil.example"},
        {"origin": "https://evil.example", "referer": "http://localhost:5173/"},
        {"referer": "http://localhost:5173@evil.example/"},
        {"referer": "http://[invalid"},
    ],
)
def test_csrf_rejects_missing_or_untrusted_source(headers: dict[str, str]) -> None:
    request = Request(
        {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    )

    with pytest.raises(AppError) as error:
        require_trusted_origin(request, local_settings())

    assert error.value.status_code == 403
    assert error.value.body.code == "CSRF_ORIGIN_DENIED"


@pytest.mark.parametrize("deployed", [False, True])
def test_refresh_cookie_is_host_only_and_never_readable_by_javascript(deployed: bool) -> None:
    settings = Settings(
        _env_file=None,
        env=Env.PRODUCTION if deployed else Env.TEST,
        jwt_secret=SecretStr("valid-test-secret-that-has-32-bytes"),
        frontend_url="https://example.com" if deployed else "http://localhost:5173",
    )
    response = Response()
    expires = datetime.now(UTC) + timedelta(days=30)

    set_refresh_cookie(response, "opaque-token", expires, settings)
    cookie = SimpleCookie(response.headers["set-cookie"])["refresh_token"]

    assert cookie.value == "opaque-token"
    assert cookie["httponly"]
    assert bool(cookie["secure"]) is deployed
    assert cookie["samesite"] == "strict"
    assert cookie["path"] == "/api/v1/auth"
    assert not cookie["domain"]
    assert 2591998 <= int(cookie["max-age"]) <= 2592000
    assert response.headers["cache-control"] == "no-store"


async def test_limiter_sets_retry_after_without_exposing_identity() -> None:
    redis = AsyncMock(spec=Redis)
    redis.eval = AsyncMock(return_value=[11, 59])
    limiter = AuthRateLimiter(redis)

    with pytest.raises(AppError) as error:
        await limiter.enforce("register", "user@example.com", 10, 3600)

    assert error.value.status_code == 429
    assert error.value.headers == {"Retry-After": "59"}
    assert "user@example.com" not in rate_limit_key("register", "user@example.com")


async def test_limiter_fails_closed_when_redis_unavailable() -> None:
    redis = AsyncMock(spec=Redis)
    redis.eval.side_effect = RedisConnectionError("private-host")

    with pytest.raises(AppError) as error:
        await AuthRateLimiter(redis).enforce("register", "127.0.0.1", 10, 3600)

    assert error.value.status_code == 503
    assert "private-host" not in str(error.value)


async def test_resend_cooldown_failure_uses_safe_error() -> None:
    redis = AsyncMock(spec=Redis)
    redis.set.side_effect = RedisConnectionError("private-host")

    with pytest.raises(AppError) as error:
        await AuthRateLimiter(redis).start_verification_cooldown("user@example.com")

    assert error.value.status_code == 503


async def test_failed_publish_cleanup_does_not_override_original_failure() -> None:
    redis = AsyncMock(spec=Redis)
    redis.eval.side_effect = RedisConnectionError("private-host")

    await AuthRateLimiter(redis).release_verification_cooldown("user@example.com", "lease")
