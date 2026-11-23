from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskPatch
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


async def test_date_locked_task_stays_unscheduled_without_changing_target_plan(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    user_id, target_day = user.id, DAY + timedelta(days=1)
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(user_id, target_day, ScheduleTrigger.MANUAL_EDIT)
    repository = ScheduleRepository(session)
    target = (await repository.active(user_id, (target_day,)))[target_day]
    target_id, target_version = target.id, target.version
    task = await make_task(session, user, planned_date=DAY, duration_min=180, is_date_locked=True)
    task_id = task.id
    result = await scheduler.replan(
        user_id, DAY, ScheduleTrigger.MANUAL_EDIT, allow_date_change=True
    )
    await session.commit()
    session.expire_all()
    stored = await session.get(Task, task_id)
    assert stored is not None and stored.is_date_locked is True
    assert stored.planned_date == DAY and stored.moved_from_date is None
    assert stored.status == TaskStatus.PENDING
    assert not result.plan.moves and not result.plan.future_plans
    assert not result.plan.recommendations
    active = await repository.active(user_id, (DAY, target_day))
    assert (active[target_day].id, active[target_day].version) == (target_id, target_version)
    details = await ScheduleReader(session).get_details(user_id, DAY)
    assert details is not None and not details.recommendations
    explanation = next(item for item in details.unscheduled_explanations if item.task_id == task_id)
    assert "DATE_CHANGE_FORBIDDEN" in explanation.reason_codes
    assert "оставлена на выбранной дате без времени" in explanation.explanation


async def test_manual_date_patch_preserves_date_lock_and_updates_both_days(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    user_id, target_day = user.id, DAY + timedelta(days=1)
    task = await make_task(session, user, planned_date=DAY, is_date_locked=True)
    task_id = task.id
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    await session.refresh(task)
    version = task.version
    await session.commit()
    tasks = TaskService(session, CLOCK, coordinator=scheduler)
    moved = await tasks.patch(user_id, task_id, TaskPatch(version=version, planned_date=target_day))
    assert moved.planned_date == target_day
    session.expire_all()
    stored = await session.get(Task, task_id)
    assert stored is not None and stored.is_date_locked is True
    assert stored.moved_from_date is None
    active = await ScheduleRepository(session).active(user_id, (DAY, target_day))
    assert set(active) == {DAY, target_day}
    assert active[DAY].version == 2
    assert not any(saved.task_id == task_id for saved in active[DAY].slots)
    assert any(saved.task_id == task_id for saved in active[target_day].slots)
