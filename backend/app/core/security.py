import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.users.models import User

JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
OPAQUE_TOKEN_BYTES = 32
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$i/dVSv2RHFlA+j2Nye40AQ$"
    "8aFjreBQ2ifXhdPXuCKxdEkOL77zxnHKJ/K/ymintQw"
)

_password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_prefix}/auth/login",
    auto_error=False,
)


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: UUID


class PasswordPolicyError(ValueError):
    pass


class InvalidAccessTokenError(ValueError):
    pass


class AccessTokenClaims(BaseModel):
    sub: UUID
    sid: UUID
    iat: Annotated[int, Field(strict=True)]
    exp: Annotated[int, Field(strict=True)]

    @model_validator(mode="after")
    def valid_lifetime(self) -> "AccessTokenClaims":
        if self.exp <= self.iat:
            raise ValueError("Срок действия токена должен быть положительным")
        return self


def validate_password(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("Пароль должен содержать от 8 до 128 символов")
    if not any(character.isalpha() for character in password):
        raise PasswordPolicyError("Пароль должен содержать хотя бы одну букву")
    if not any(character.isdigit() for character in password):
        raise PasswordPolicyError("Пароль должен содержать хотя бы одну цифру")
    return password


async def hash_password(password: str) -> str:
    validate_password(password)
    return await run_in_threadpool(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return await run_in_threadpool(_password_hash.verify, password, password_hash)
    except UnknownHashError:
        return False


def generate_token() -> str:
    return secrets.token_urlsafe(OPAQUE_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise RuntimeError("Для работы с JWT необходимо задать JWT_SECRET")
    return settings.jwt_secret.get_secret_value()


def create_access_token(
    user_id: UUID,
    session_id: UUID,
    settings: Settings | None = None,
    *,
    now: datetime | None = None,
) -> str:
    settings = settings or get_settings()
    issued_at = now if now is not None else datetime.now(UTC)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("Время выпуска токена должно содержать часовой пояс")
    claims = AccessTokenClaims(
        sub=user_id,
        sid=session_id,
        iat=int(issued_at.timestamp()),
        exp=int((issued_at + timedelta(minutes=settings.access_ttl_min)).timestamp()),
    )
    return jwt.encode(
        claims.model_dump(mode="json"), _jwt_secret(settings), algorithm=JWT_ALGORITHM
    )


def decode_access_token(token: str, settings: Settings | None = None) -> AccessTokenClaims:
    settings = settings or get_settings()
    secret = _jwt_secret(settings)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "sid", "iat", "exp"]},
        )
        return AccessTokenClaims.model_validate(payload)
    except (InvalidTokenError, ValidationError):
        raise InvalidAccessTokenError("Недействительный access-токен") from None


def authentication_required() -> AppError:
    return AppError(401, "AUTHENTICATION_REQUIRED", "Необходима аутентификация")


def validate_authentication_state(
    user: User | None,
    device: AuthSession | None,
    now: datetime,
) -> None:
    if (
        user is None
        or not user.is_active
        or user.deleted_at is not None
        or device is None
        or device.user_id != user.id
        or device.revoked_at is not None
        or device.expires_at <= now
    ):
        raise authentication_required()
    if not user.is_email_verified:
        raise AppError(403, "EMAIL_NOT_VERIFIED", "Подтвердите email")


async def get_auth_context(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    if not token:
        raise authentication_required()
    if settings.jwt_secret is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен")
    try:
        claims = decode_access_token(token, settings)
    except InvalidAccessTokenError:
        raise authentication_required() from None
    async with session.begin():
        state = await AuthRepository(session).authentication_state(claims.sub, claims.sid)
        if state is None:
            raise authentication_required()
        user, device = state
        validate_authentication_state(user, device, datetime.now(UTC))
    return AuthContext(user=user, session_id=device.id)


async def get_current_user(context: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return context.user
