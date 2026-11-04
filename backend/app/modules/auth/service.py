from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import AuthRateLimiter, unavailable
from app.core.security import create_access_token, generate_token, hash_password, hash_token
from app.modules.auth.delivery import VerificationPublisher, VerificationPublishError
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
            expires_at = now + timedelta(days=self.settings.refresh_ttl_days)
            refresh_token = generate_token()
            device = await self.repository.create_session(
                user.id, hash_token(refresh_token), now, expires_at, ip, user_agent
            )
            access_token = create_access_token(user.id, device.id, self.settings, now=now)
        return IssuedSession(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            expires_in=self.settings.access_ttl_min * 60,
        )
