from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger, SlotKind
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.dependencies import get_task_changed_handler
from app.modules.tasks.models import TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskPatch
from app.modules.tasks.service import TaskService
from tests.db.test_schedule_service import CLOCK, DAY, setup_user

pytestmark = pytest.mark.docker
TARGET = DAY + timedelta(days=1)


async def service(session: AsyncSession, *, completed: bool = True) -> tuple[UUID, TaskService]:
    user = await setup_user(session, completed=completed)
    user_id = user.id
    await session.commit()
    scheduler = ScheduleService(session, CLOCK)
    return user_id, TaskService(session, CLOCK, get_task_changed_handler(scheduler))


def body() -> TaskCreate:
    return TaskCreate(title="Task", type="routine", duration_min=30, planned_date=TARGET)


async def active(session: AsyncSession, user_id: UUID) -> list[Schedule]:
    async with session.begin():
        return list(
            await session.scalars(
                select(Schedule)
                .where(Schedule.user_id == user_id, Schedule.is_active.is_(True))
                .order_by(Schedule.date)
            )
        )


async def test_creation_replans_and_returns_current_task_version(session: AsyncSession) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    assert created.status == TaskStatus.SCHEDULED
    assert created == await tasks.get(user_id, created.id)
    plans = await active(session, user_id)
    assert len(plans) == 1
    assert plans[0].date == TARGET and plans[0].trigger == ScheduleTrigger.TASK_CREATED
    async with session.begin():
        slot = await session.scalar(
            select(ScheduleSlot).where(
                ScheduleSlot.schedule_id == plans[0].id, ScheduleSlot.kind == SlotKind.TASK
            )
        )
        assert slot is not None and slot.task_id == created.id


async def test_move_updates_both_dates_and_delete_removes_future_slot(
    session: AsyncSession,
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    moved = await tasks.patch(
        user_id,
        created.id,
        TaskPatch(version=created.version, planned_date=TARGET + timedelta(days=1)),
    )
    assert moved == await tasks.get(user_id, created.id)
    plans = await active(session, user_id)
    assert [plan.date for plan in plans] == [TARGET, TARGET + timedelta(days=1)]
    assert all(plan.trigger == ScheduleTrigger.TASK_UPDATED for plan in plans)
    await tasks.delete(user_id, moved.id, moved.version)
    plans = await active(session, user_id)
    async with session.begin():
        remaining = await session.scalar(
            select(func.count())
            .select_from(ScheduleSlot)
            .where(
                ScheduleSlot.schedule_id.in_([plan.id for plan in plans]),
                ScheduleSlot.task_id == moved.id,
            )
        )
        assert remaining == 0
    assert plans[-1].trigger == ScheduleTrigger.TASK_DELETED


async def test_content_changes_and_noop_do_not_create_schedule_versions(
    session: AsyncSession,
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    before = [(plan.id, plan.version) for plan in await active(session, user_id)]
    changed = await tasks.patch(
        user_id, created.id, TaskPatch(version=created.version, title="Renamed", description="Text")
    )
    await tasks.patch(user_id, created.id, TaskPatch(version=changed.version, title="Renamed"))
    assert [(plan.id, plan.version) for plan in await active(session, user_id)] == before


@pytest.mark.parametrize("operation", ["complete", "skip"])
async def test_status_changes_and_reopen_refresh_schedule(
    session: AsyncSession, operation: str
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    command = tasks.complete if operation == "complete" else tasks.skip
    changed = await command(user_id, created.id, created.version)
    plans = await active(session, user_id)
    assert plans[0].trigger == ScheduleTrigger.STATUS_CHANGED and plans[0].version == 2
    assert changed.status == (TaskStatus.DONE if operation == "complete" else TaskStatus.SKIPPED)
    reopened = await tasks.reopen(user_id, created.id, changed.version)
    assert reopened.status == TaskStatus.SCHEDULED
    assert reopened == await tasks.get(user_id, reopened.id)
    assert (await active(session, user_id))[0].version == 3


async def test_incomplete_onboarding_keeps_task_without_schedule(session: AsyncSession) -> None:
    user_id, tasks = await service(session, completed=False)
    created = await tasks.create(user_id, body())
    assert created.status == TaskStatus.PENDING and created.version == 1
    assert await active(session, user_id) == []
