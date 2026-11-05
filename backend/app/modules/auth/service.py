from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import AuthRateLimiter, unavailable
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    AuthContext,
    authentication_required,
    create_access_token,
    generate_token,
    hash_password,
    hash_token,
    validate_authentication_state,
    verify_password,
)
from app.modules.auth.delivery import VerificationPublisher, VerificationPublishError
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository


@dataclass(frozen=True)
class IssuedSession:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: datetime
    expires_in: int


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        limiter: AuthRateLimiter,
        publisher: VerificationPublisher,
    ) -> None:
        self.session = session
        self.repository = AuthRepository(session)
        self.settings = settings
        self.limiter = limiter
        self.publisher = publisher

    async def _issue_session(
        self,
        user_id: UUID,
        now: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        expires_at = now + timedelta(days=self.settings.refresh_ttl_days)
        refresh_token = generate_token()
        device = await self.repository.create_session(
            user_id, hash_token(refresh_token), now, expires_at, ip, user_agent
        )
        return IssuedSession(
            access_token=create_access_token(user_id, device.id, self.settings, now=now),
            refresh_token=refresh_token,
            expires_at=expires_at,
            expires_in=self.settings.access_ttl_min * 60,
        )

    async def _lock_context(self, context: AuthContext) -> AuthSession:
        user = await self.repository.lock_user(context.user.id)
        device = await self.repository.lock_session(context.session_id, context.user.id)
        validate_authentication_state(user, device, datetime.now(UTC))
        if device is None:
            raise authentication_required()
        return device

    async def _publish(self, email: str, token: str, expires_at: datetime, lease: str) -> None:
        try:
            await self.publisher.publish(email, token, expires_at)
        except VerificationPublishError:
            await self.limiter.release_verification_cooldown(email, lease)
            raise unavailable() from None

    async def register(self, email: str, password: str) -> None:
        password_hash = await hash_password(password)
        async with self.session.begin():
            user = await self.repository.create_user(email, password_hash)
            if user is None:
                return
            lease = await self.limiter.start_verification_cooldown(email, initial=True)
            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=self.settings.email_verification_ttl_hours)
            token = generate_token()
            await self.repository.add_verification_token(
                user.id, hash_token(token), now, expires_at
            )
        await self._publish(email, token, expires_at, lease)

    async def resend_verification(self, email: str) -> None:
        lease = await self.limiter.start_verification_cooldown(email)
        async with self.session.begin():
            user = await self.repository.lock_user_by_email(email)
            if user is None or not user.is_active or user.deleted_at or user.is_email_verified:
                return
            now = datetime.now(UTC)
            expires_at = now + timedelta(hours=self.settings.email_verification_ttl_hours)
            token = generate_token()
            await self.repository.invalidate_verification_tokens(user.id, now)
            await self.repository.add_verification_token(
                user.id, hash_token(token), now, expires_at
            )
        await self._publish(email, token, expires_at, lease)

    async def verify_email(
        self,
        token: str,
        ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        if self.settings.jwt_secret is None:
            raise unavailable()
        digest = hash_token(token)
        async with self.session.begin():
            user_id = await self.repository.verification_owner(digest)
            user = await self.repository.lock_user(user_id) if user_id is not None else None
            email_token = await self.repository.lock_verification_token(digest)
            now = datetime.now(UTC)
            if (
                user is None
                or not user.is_active
                or user.deleted_at is not None
                or user.is_email_verified
                or email_token is None
                or email_token.used_at is not None
                or email_token.expires_at <= now
            ):
                raise AppError(400, "INVALID_EMAIL_TOKEN", "Ссылка недействительна или устарела")
            await self.repository.invalidate_verification_tokens(user.id, now)
            user.is_email_verified = True
            issued = await self._issue_session(user.id, now, ip, user_agent)
        return issued

    async def login(
        self,
        email: str,
        password: str,
        ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        if self.settings.jwt_secret is None:
            raise unavailable()
        async with self.session.begin():
            user = await self.repository.lock_user_by_email(email)
            password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
            valid_password = await verify_password(password, password_hash)
            if (
                not valid_password
                or user is None
                or not user.is_active
                or user.deleted_at is not None
            ):
                raise AppError(401, "INVALID_CREDENTIALS", "Неверный email или пароль")
            if not user.is_email_verified:
                raise AppError(403, "EMAIL_NOT_VERIFIED", "Подтвердите email")
            issued = await self._issue_session(user.id, datetime.now(UTC), ip, user_agent)
        return issued

    async def refresh(
        self,
        token: str | None,
        ip: str | None,
        user_agent: str | None,
    ) -> IssuedSession:
        if not token or len(token) > 256:
            raise AppError(401, "INVALID_REFRESH_TOKEN", "Сессия недействительна")
        if self.settings.jwt_secret is None:
            raise unavailable()
        digest = hash_token(token)
        issued: IssuedSession | None = None
        async with self.session.begin():
            owner = await self.repository.refresh_owner(digest)
            if owner is None:
                raise AppError(401, "INVALID_REFRESH_TOKEN", "Сессия недействительна")
            user_id, session_id = owner
            user = await self.repository.lock_user(user_id)
            device = await self.repository.lock_session(session_id, user_id)
            previous = await self.repository.lock_refresh_token(digest)
            now = datetime.now(UTC)
            if (
                previous is not None
                and device is not None
                and previous.session_id == device.id
                and previous.used_at is not None
            ):
                if device.revoked_at is None:
                    device.revoked_at = now
            elif (
                user is not None
                and user.is_active
                and user.deleted_at is None
                and user.is_email_verified
                and device is not None
                and device.revoked_at is None
                and device.expires_at > now
                and previous is not None
                and previous.session_id == device.id
                and previous.expires_at > now
            ):
                replacement = generate_token()
                await self.repository.rotate_refresh_token(
                    previous, hash_token(replacement), now, device.expires_at
                )
                device.last_used_at = now
                if ip is not None:
                    device.ip = ip
                if user_agent is not None:
                    device.user_agent = user_agent
                issued = IssuedSession(
                    access_token=create_access_token(user_id, device.id, self.settings, now=now),
                    refresh_token=replacement,
                    expires_at=device.expires_at,
                    expires_in=self.settings.access_ttl_min * 60,
                )
        if issued is None:
            raise AppError(401, "INVALID_REFRESH_TOKEN", "Сессия недействительна")
        return issued

    async def logout(self, token: str | None) -> None:
        if not token or len(token) > 256:
            return
        async with self.session.begin():
            owner = await self.repository.refresh_owner(hash_token(token))
            if owner is None:
                return
            user_id, session_id = owner
            user = await self.repository.lock_user(user_id)
            if user is None:
                return
            device = await self.repository.lock_session(session_id, user_id)
            if device is not None and device.revoked_at is None:
                device.revoked_at = datetime.now(UTC)

    async def logout_all(self, context: AuthContext) -> None:
        async with self.session.begin():
            await self._lock_context(context)
            await self.repository.revoke_all_sessions(context.user.id, datetime.now(UTC))

    async def sessions(self, context: AuthContext) -> list[AuthSession]:
        async with self.session.begin():
            await self._lock_context(context)
            devices = await self.repository.active_sessions(context.user.id, datetime.now(UTC))
        return devices

    async def revoke_session(self, context: AuthContext, session_id: UUID) -> bool:
        async with self.session.begin():
            await self._lock_context(context)
            device = await self.repository.lock_session(session_id, context.user.id)
            if device is None:
                raise AppError(404, "SESSION_NOT_FOUND", "Сессия не найдена")
            if device.revoked_at is None:
                device.revoked_at = datetime.now(UTC)
        return session_id == context.session_id
