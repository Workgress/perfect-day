from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger, SlotKind
from app.modules.tasks.models import Task, TaskType
from app.modules.users.models import User

DAY = date(2026, 10, 27)


async def make_user(session: AsyncSession, email: str = "user@example.ru") -> User:
    user = User(email=email, password_hash="hash")
    session.add(user)
    await session.flush()
    return user


async def make_task(session: AsyncSession, user: User, **overrides: Any) -> Task:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "title": "Отчёт",
        "type": TaskType.INTELLECTUAL,
        "duration_min": 60,
        "planned_date": DAY,
    }
    fields.update(overrides)
    task = Task(**fields)
    session.add(task)
    await session.flush()
    return task


async def make_schedule(session: AsyncSession, user: User, **overrides: Any) -> Schedule:
    fields: dict[str, Any] = {
        "user_id": user.id,
        "date": DAY,
        "algorithm_version": "1.0.0",
        "trigger": ScheduleTrigger.INITIAL,
    }
    fields.update(overrides)
    schedule = Schedule(**fields)
    session.add(schedule)
    await session.flush()
    return schedule


async def make_slot(
    session: AsyncSession,
    schedule: Schedule,
    task: Task | None = None,
    **overrides: Any,
) -> ScheduleSlot:
    fields: dict[str, Any] = {
        "schedule_id": schedule.id,
        "task_id": task.id if task else None,
        "kind": SlotKind.TASK if task else SlotKind.BREAK,
        "start_at": datetime(2026, 10, 27, 10, 0, tzinfo=UTC),
        "end_at": datetime(2026, 10, 27, 11, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    slot = ScheduleSlot(**fields)
    session.add(slot)
    await session.flush()
    return slot
