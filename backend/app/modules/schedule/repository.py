"""Owner-scoped persistence; callers own transactions and lock the user before mutation."""

from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.schedule.models import OnboardingCompletion, Schedule
from app.modules.tasks.models import Task
from app.modules.users.repository import ProfileRepository


class ScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_user(self, user_id: UUID) -> bool:
        # A parent row also serializes first schedules (there may be no schedule to lock).
        # One owner lock covers source + transfer targets without cross-date deadlocks.
        return await ProfileRepository(self.session).get_user(user_id, for_update=True) is not None

    async def receipt(self, user_id: UUID, key: UUID) -> OnboardingCompletion | None:
        return await self.session.get(OnboardingCompletion, (user_id, key), populate_existing=True)

    async def active(self, user_id: UUID, days: tuple[date, ...]) -> dict[date, Schedule]:
        rows = await self.session.scalars(
            select(Schedule)
            .where(
                Schedule.user_id == user_id, Schedule.date.in_(days), Schedule.is_active.is_(True)
            )
            .options(selectinload(Schedule.slots))
            .order_by(Schedule.date)
            .execution_options(populate_existing=True)
        )
        return {row.date: row for row in rows}

    async def tasks(self, user_id: UUID, days: tuple[date, ...], history: set[UUID]) -> list[Task]:
        rows = await self.session.scalars(
            select(Task)
            .where(
                Task.user_id == user_id,
                or_(
                    (Task.planned_date.in_(days) & Task.deleted_at.is_(None)), Task.id.in_(history)
                ),
            )
            .order_by(Task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(rows)

    async def next_version(self, user_id: UUID, day: date) -> int:
        maximum = await self.session.scalar(
            select(func.max(Schedule.version)).where(
                Schedule.user_id == user_id, Schedule.date == day
            )
        )
        return int(maximum or 0) + 1

    async def active_dates(self, user_id: UUID, since: date) -> tuple[date, ...]:
        rows = await self.session.scalars(
            select(Schedule.date)
            .where(
                Schedule.user_id == user_id, Schedule.is_active.is_(True), Schedule.date >= since
            )
            .order_by(Schedule.date)
        )
        return tuple(rows)
