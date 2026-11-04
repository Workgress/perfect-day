from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import AuthRateLimiter
from app.core.redis import get_redis
from app.db.session import get_session
from app.modules.auth.delivery import VerificationPublisher, get_verification_publisher
from app.modules.auth.service import AuthService


def get_auth_limiter(redis: Annotated[Redis, Depends(get_redis)]) -> AuthRateLimiter:
    return AuthRateLimiter(redis)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[AuthRateLimiter, Depends(get_auth_limiter)],
    publisher: Annotated[VerificationPublisher, Depends(get_verification_publisher)],
) -> AuthService:
    return AuthService(session, settings, limiter, publisher)


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
