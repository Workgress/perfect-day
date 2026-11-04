import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import BaseModel, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings

JWT_ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
OPAQUE_TOKEN_BYTES = 32

_password_hash = PasswordHash.recommended()


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
