from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import AuthRateLimiter
from app.core.redis import get_redis
from app.core.security import AuthContext, get_auth_context
from app.db.session import get_session
from app.modules.auth.delivery import (
    VerificationPublisher,
    get_password_reset_publisher,
    get_verification_publisher,
)
from app.modules.auth.schemas import EmailRequest
from app.modules.auth.service import AuthService


def get_auth_limiter(redis: Annotated[Redis, Depends(get_redis)]) -> AuthRateLimiter:
    return AuthRateLimiter(redis)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
    publisher: Annotated[VerificationPublisher, Depends(get_verification_publisher)],
    password_publisher: Annotated[VerificationPublisher, Depends(get_password_reset_publisher)],
) -> AuthService:
    return AuthService(session, settings, limiter, publisher, password_publisher)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def limit_registration(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("register", client_ip(request), 10, 3600)


async def limit_verification(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("verify-email", client_ip(request), 30, 60)


async def limit_resend(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("resend-verification", client_ip(request), 30, 60)


async def limit_login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    try:
        email = str(EmailRequest.model_validate({"email": form.username}).email)
    except ValidationError:
        email = form.username.strip().lower()
    identity = f"{client_ip(request)}\0{email}"
    await limiter.enforce("login", identity, 5, 60)


async def limit_refresh(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("refresh", client_ip(request), 30, 60)


async def limit_logout(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("logout", client_ip(request), 30, 60)


async def limit_forgot_password(
    request: Request,
    body: EmailRequest,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("password-forgot-ip", client_ip(request), 3, 3600)
    await limiter.enforce("password-forgot-email", str(body.email), 3, 3600)


async def limit_reset_password(
    request: Request,
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("password-reset", client_ip(request), 30, 60)


async def limit_change_password(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
) -> None:
    await limiter.enforce("password-change", str(context.user.id), 5, 60)
