from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, UserProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        # Lock the parent even if there is no profile yet: concurrent initial
        # PATCH requests must not both try to insert the same profile.
        statement = (
            select(User)
            .where(User.id == user_id, User.is_active.is_(True), User.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get(self, user_id: UUID) -> UserProfile | None:
        statement = (
            select(UserProfile)
            .join(User, User.id == UserProfile.user_id)
            .where(
                UserProfile.user_id == user_id, User.is_active.is_(True), User.deleted_at.is_(None)
            )
            .execution_options(populate_existing=True)
        )
        return await self.session.scalar(statement)

    async def save(self, profile: UserProfile) -> None:
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(profile)
