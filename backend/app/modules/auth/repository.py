from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthSession, EmailToken, EmailTokenPurpose, RefreshToken
from app.modules.users.models import User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_user(self, email: str, password_hash: str) -> User | None:
        statement = (
            insert(User)
            .values(email=email, password_hash=password_hash)
            .on_conflict_do_nothing(index_elements=[User.email])
            .returning(User)
        )
        return await self.session.scalar(statement)

    async def lock_user_by_email(self, email: str) -> User | None:
        return await self.session.scalar(
            select(User)
            .where(User.email == email)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def lock_user(self, user_id: UUID) -> User | None:
        return await self.session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def authentication_state(
        self, user_id: UUID, session_id: UUID
    ) -> tuple[User, AuthSession] | None:
        result = await self.session.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(User.id == user_id, AuthSession.id == session_id)
            .execution_options(populate_existing=True)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def lock_session(self, session_id: UUID, user_id: UUID) -> AuthSession | None:
        return await self.session.scalar(
            select(AuthSession)
            .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def refresh_owner(self, token_hash: str) -> tuple[UUID, UUID] | None:
        result = await self.session.execute(
            select(AuthSession.user_id, AuthSession.id)
            .join(RefreshToken, RefreshToken.session_id == AuthSession.id)
            .where(RefreshToken.token_hash == token_hash)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row is not None else None

    async def lock_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return await self.session.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def rotate_refresh_token(
        self,
        previous: RefreshToken,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        previous.used_at = now
        await self.session.flush()
        replacement = RefreshToken(
            session_id=previous.session_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
        )
        self.session.add(replacement)
        await self.session.flush()
        previous.replaced_by_id = replacement.id
        await self.session.flush()

    async def active_sessions(self, user_id: UUID, now: datetime) -> list[AuthSession]:
        result = await self.session.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.last_used_at.desc(), AuthSession.id)
        )
        return list(result)

    async def revoke_all_sessions(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def verification_owner(self, token_hash: str) -> UUID | None:
        return await self.session.scalar(
            select(EmailToken.user_id).where(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == EmailTokenPurpose.VERIFY_EMAIL,
            )
        )

    async def lock_verification_token(self, token_hash: str) -> EmailToken | None:
        return await self.session.scalar(
            select(EmailToken)
            .where(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == EmailTokenPurpose.VERIFY_EMAIL,
            )
            .with_for_update()
        )

    async def invalidate_verification_tokens(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(EmailToken)
            .where(
                EmailToken.user_id == user_id,
                EmailToken.purpose == EmailTokenPurpose.VERIFY_EMAIL,
                EmailToken.used_at.is_(None),
            )
            .values(used_at=now)
        )

    async def add_verification_token(
        self,
        user_id: UUID,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        self.session.add(
            EmailToken(
                user_id=user_id,
                purpose=EmailTokenPurpose.VERIFY_EMAIL,
                token_hash=token_hash,
                created_at=now,
                expires_at=expires_at,
            )
        )
        await self.session.flush()

    async def create_session(
        self,
        user_id: UUID,
        refresh_hash: str,
        now: datetime,
        expires_at: datetime,
        ip: str | None,
        user_agent: str | None,
    ) -> AuthSession:
        device = AuthSession(
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
            last_used_at=now,
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(device)
        await self.session.flush()
        self.session.add(
            RefreshToken(
                session_id=device.id,
                token_hash=refresh_hash,
                created_at=now,
                expires_at=expires_at,
            )
        )
        await self.session.flush()
        return device
