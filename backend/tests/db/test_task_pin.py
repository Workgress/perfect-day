import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.events import TaskChanged
from app.modules.tasks.models import Task
from app.modules.tasks.placement_schemas import TaskPinRequest
from app.modules.tasks.placement_service import TaskPlacementService
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import TaskService
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker
TARGET = DAY + timedelta(days=1)


def at(hour: int, minute: int = 0, *, day=DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


async def seed(session: AsyncSession) -> tuple[UUID, Any, TaskPlacementService, list[TaskChanged]]:
    user = await setup_user(session, completed=True)
    owner = user.id
    await session.commit()
    scheduler = ScheduleService(session, CLOCK)
    task = await TaskService(session, CLOCK, coordinator=scheduler).create(
        owner, TaskCreate(title="Отчёт", type="routine", duration_min=30, planned_date=DAY)
    )
    events = []

    async def notify(event: TaskChanged) -> None:
        assert not session.in_transaction()
        events.append(event)

    return owner, task, TaskPlacementService(session, CLOCK, scheduler, notify), events


def command(task: Any, *, start=None, day=DAY, versions=None) -> TaskPinRequest:
    return TaskPinRequest(
        planned_date=day,
        start_at=start or at(9, 7, day=day),
        version=task.version,
        schedule_versions=versions if versions is not None else {DAY: 1},
    )


async def test_pin_persists_exact_interval_and_repeat_and_event_replay_are_noops(
    session: AsyncSession,
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    assert pinned.is_pinned is True and pinned.pinned_start == at(9, 7)
    assert pinned.version == task.version + 1 and pinned.actual_start is None
    async with session.begin():
        plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        slot = next(item for item in plan.slots if item.task_id == task.id)
        assert plan.version == 2 and slot.is_pinned is True
        assert (slot.start_at, slot.end_at) == (at(9, 7), at(9, 37))
    before = await snapshot(session)
    repeated = await placement.pin(owner, task.id, command(pinned, versions={DAY: 2}))
    assert repeated == pinned and await snapshot(session) == before
    assert len(events) == 1
    await placement.scheduler.task_changed(events[0])
    assert await snapshot(session) == before
    with pytest.raises(AppError) as error:
        await placement.pin(owner, task.id, command(task))
    assert error.value.body.code == "TASK_VERSION_CONFLICT"
    assert await snapshot(session) == before


async def test_pin_replaces_existing_future_pin_and_updates_both_dates(
    session: AsyncSession,
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    pinned = await placement.pin(owner, task.id, command(pinned, start=at(10), versions={DAY: 2}))
    async with session.begin():
        stored = await session.get(Task, task.id)
        stored.is_date_locked = True
    transferred = await placement.pin(
        owner, task.id, command(pinned, day=TARGET, versions={DAY: 3, TARGET: 0})
    )
    assert transferred.planned_date == TARGET and transferred.pinned_start == at(9, 7, day=TARGET)
    assert transferred.is_date_locked is True and len(events) == 3
    async with session.begin():
        plans = await placement.scheduler.repository.active(owner, (DAY, TARGET))
        assert plans[DAY].version == 4 and plans[TARGET].version == 1
        assert not any(slot.task_id == task.id for slot in plans[DAY].slots)
        assert any(slot.task_id == task.id and slot.is_pinned for slot in plans[TARGET].slots)
        stored = await session.get(Task, task.id)
        assert stored.moved_from_date is None


@pytest.mark.parametrize("failure_day", [DAY, TARGET])
async def test_pin_rolls_back_task_receipt_and_both_plans_on_storage_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure_day: Any
) -> None:
    owner, task, placement, events = await seed(session)
    before = await snapshot(session)
    original = placement.scheduler._save_plan

    async def fail_after_save(owner_id, plan, trigger):
        result = await original(owner_id, plan, trigger)
        if plan.day == failure_day:
            raise RuntimeError("storage failure")
        return result

    monkeypatch.setattr(placement.scheduler, "_save_plan", fail_after_save)
    with pytest.raises(RuntimeError, match="storage failure"):
        await placement.pin(owner, task.id, command(task, day=TARGET, versions={DAY: 1, TARGET: 0}))
    assert not events and await snapshot(session) == before


@pytest.mark.parametrize("protection", ["started", "past", "actual"])
async def test_pin_cannot_move_protected_intervals(session: AsyncSession, protection: str) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    if protection == "actual":
        async with session.begin():
            row = await session.get(Task, task.id)
            row.actual_start = CLOCK.now()
    else:
        placement.clock = FrozenClock(at(10) if protection == "past" else at(9, 10))
    before = await snapshot(session)
    with pytest.raises(AppError) as error:
        await placement.pin(owner, task.id, command(pinned, start=at(14), versions={DAY: 2}))
    assert error.value.body.code == "TASK_MOVE_NOT_ALLOWED"
    assert error.value.body.details["reason_code"] == (
        "TASK_ALREADY_RESERVED" if protection == "past" else "TASK_STARTED"
    )
    assert await snapshot(session) == before and len(events) == 1


async def test_pin_rolls_back_on_calculation_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, task, placement, events = await seed(session)
    before = await snapshot(session)

    def unavailable(*args):
        raise RuntimeError("private calculation failure")

    monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", unavailable)
    with pytest.raises(AppError) as error:
        await placement.pin(owner, task.id, command(task))
    assert error.value.status_code == 503 and error.value.body.code == "PLANNER_UNAVAILABLE"
    assert not events and await snapshot(session) == before


@pytest.mark.parametrize(
    ("kind", "minutes", "reason"),
    [
        ("intellectual", 180, "INTENSITY_CAPACITY_EXCEEDED"),
        ("routine", 480, "DAY_CAPACITY_EXCEEDED"),
    ],
)
async def test_pin_enforces_critical_day_limits(
    session: AsyncSession, kind: str, minutes: int, reason: str
) -> None:
    user = await setup_user(session, completed=True, elapsed=14)
    profile = await session.get(UserProfile, user.id)
    profile.lunch_duration_min = 0
    task = await make_task(session, user, planned_date=DAY, type=kind, duration_min=minutes)
    owner, task_id, version = user.id, task.id, task.version
    await session.commit()
    before = await snapshot(session)
    placement = TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK))
    with pytest.raises(AppError) as error:
        await placement.pin(
            owner,
            task_id,
            TaskPinRequest(
                planned_date=DAY, start_at=at(8), version=version, schedule_versions={DAY: 0}
            ),
        )
    assert error.value.body.code == "TASK_MOVE_NOT_ALLOWED"
    assert error.value.body.details["reason_code"] == reason
    assert await snapshot(session) == before


async def test_pin_requires_break_between_intellectual_tasks(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await make_task(
        session, user, planned_date=DAY, duration_min=60, is_pinned=True, pinned_start=at(8)
    )
    task = await make_task(session, user, planned_date=DAY, duration_min=30)
    owner, task_id, version = user.id, task.id, task.version
    await session.commit()
    placement = TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK))
    with pytest.raises(AppError) as error:
        await placement.pin(
            owner,
            task_id,
            TaskPinRequest(
                planned_date=DAY, start_at=at(9, 5), version=version, schedule_versions={DAY: 0}
            ),
        )
    assert error.value.body.code == "TASK_MOVE_NOT_ALLOWED"
    assert error.value.body.details["reason_code"] == "INSUFFICIENT_BREAK"


async def test_competing_pins_cannot_reserve_the_same_interval(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        first = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        second = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        await ScheduleService(session, CLOCK).replan(committed_owner, DAY, ScheduleTrigger.INITIAL)
        items = [(item.id, command(item)) for item in (first, second)]
        await session.commit()

    async def pin(task_id, body):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK)).pin(
                committed_owner, task_id, body
            )

    results = await asyncio.wait_for(
        asyncio.gather(*(pin(*item) for item in items), return_exceptions=True), timeout=15
    )
    errors = [item for item in results if isinstance(item, AppError)]
    assert len(errors) == 1 and errors[0].body.code == "SCHEDULE_VERSION_CONFLICT"
    async with AsyncSession(engine) as session:
        plan = (await ScheduleRepository(session).active(committed_owner, (DAY,)))[DAY]
        assert plan.version == 2
        assert (
            len([slot for slot in plan.slots if slot.is_pinned and slot.start_at == at(9, 7)]) == 1
        )
