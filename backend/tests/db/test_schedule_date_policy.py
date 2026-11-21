from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import TaskService
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user

pytestmark = pytest.mark.docker


async def test_replan_keeps_unplaced_task_date_and_leaves_target_plan_unchanged(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    user_id, target_day = user.id, DAY + timedelta(days=1)
    scheduler = ScheduleService(session, CLOCK)
    await make_task(session, user, planned_date=target_day, type="routine", duration_min=30)
    await scheduler.replan(user_id, target_day, ScheduleTrigger.TASK_CREATED)
    repository = ScheduleRepository(session)
    target = (await repository.active(user_id, (target_day,)))[target_day]
    target_id, target_version = target.id, target.version
    task = await make_task(session, user, planned_date=DAY, duration_min=60)
    task_id = task.id
    original = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    assert any(
        slot.task is not None and slot.task.task_id == task_id for slot in original.plan.slots
    )
    task.duration_min = 180
    await session.flush()
    result = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert not result.plan.moves and not result.plan.future_plans
    await session.commit()
    session.expire_all()
    stored = await session.get(Task, task_id)
    assert stored is not None and stored.planned_date == DAY and stored.moved_from_date is None
    assert stored.status == TaskStatus.PENDING
    active = await repository.active(user_id, (DAY, target_day))
    assert (active[target_day].id, active[target_day].version) == (target_id, target_version)
    assert (
        await session.scalar(
            select(ScheduleSlot.id)
            .join(Schedule)
            .where(Schedule.is_active.is_(True), ScheduleSlot.task_id == task_id)
        )
        is None
    )
    read = await ScheduleReader(session).get(user_id, DAY)
    assert read is not None
    unplaced = next(item for item in read.unscheduled if item.task_id == task_id)
    assert "INTENSITY_CAPACITY_EXCEEDED" in unplaced.reason_codes
    assert "DATE_CHANGE_FORBIDDEN" in unplaced.reason_codes
    warning = next(item for item in read.warnings if item.code == "DATE_CHANGE_FORBIDDEN")
    assert warning.task_id == task_id and DAY.isoformat() in warning.message
    assert warning.target_date is None


async def test_task_creation_replan_does_not_move_unplaced_task_implicitly(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    user_id = user.id
    await session.commit()
    tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
    created = await tasks.create(
        user_id,
        TaskCreate(title="Отчёт", type="intellectual", duration_min=180, planned_date=DAY),
    )
    assert created.planned_date == DAY and created.status == TaskStatus.PENDING
    read = await ScheduleReader(session).get(user_id, DAY)
    assert read is not None
    assert any(item.task_id == created.id for item in read.unscheduled)
    assert not read.moves and not any(slot.task_id == created.id for slot in read.slots)
