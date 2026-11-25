import asyncio
from datetime import time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleSlot, ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task
from app.modules.tasks.placement_schemas import TaskStartNowRequest
from app.modules.tasks.placement_service import TaskPlacementService
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user
from tests.db.test_task_pin import at, command, seed
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker
NOW = at(8, 7).replace(second=13, microsecond=123456)


class CountingClock:
    def __init__(self):
        self.calls = 0

    def now(self):
        instant = NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return instant


class NoClock:
    def now(self):
        raise AssertionError("A successful start must not be repeated")


@pytest.mark.parametrize("pinned", [False, True])
async def test_start_saves_one_server_time_and_preserves_history_and_repeats(
    session: AsyncSession, pinned: bool
) -> None:
    owner, task, placement, events = await seed(session)
    version = 1
    if pinned:
        task = await placement.pin(owner, task.id, command(task))
        version = 2
    async with session.begin():
        original = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        original_id = original.id
        old = next(saved for saved in original.slots if saved.task_id == task.id)
        old_interval = old.start_at, old.end_at, old.is_pinned
        row = await session.get(Task, task.id)
        row.is_date_locked = True
    clock = CountingClock()
    placement.clock = placement.scheduler.clock = clock
    started = await placement.start_now(
        owner, task.id, TaskStartNowRequest(version=task.version, schedule_versions={DAY: version})
    )
    assert clock.calls == 1 and started.actual_start == NOW
    assert started.is_pinned is pinned and started.is_date_locked
    assert started.pinned_start == (NOW if pinned else None)
    async with session.begin():
        current = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        saved = next(saved for saved in current.slots if saved.task_id == task.id)
        assert (saved.start_at, saved.end_at) == (NOW, NOW + timedelta(minutes=30))
        old = (
            await session.scalars(
                select(ScheduleSlot).where(
                    ScheduleSlot.schedule_id == original_id, ScheduleSlot.task_id == task.id
                )
            )
        ).one()
        assert (old.start_at, old.end_at, old.is_pinned) == old_interval
    placement.scheduler.clock = FrozenClock(NOW + timedelta(minutes=5))
    async with session.begin():
        await placement.scheduler.replan(owner, DAY, ScheduleTrigger.MANUAL_EDIT)
    before = await snapshot(session)
    placement.clock = NoClock()
    repeated = await placement.start_now(
        owner,
        task.id,
        TaskStartNowRequest(version=started.version, schedule_versions={DAY: version + 2}),
    )
    assert repeated == started and await snapshot(session) == before
    assert len(events) == (2 if pinned else 1)
    for task_version, plan_version, code in (
        (task.version, version, "TASK_VERSION_CONFLICT"),
        (started.version, version, "SCHEDULE_VERSION_CONFLICT"),
    ):
        with pytest.raises(AppError) as error:
            await placement.start_now(
                owner,
                task.id,
                TaskStartNowRequest(version=task_version, schedule_versions={DAY: plan_version}),
            )
        assert error.value.body.code == code and await snapshot(session) == before


async def test_start_creates_first_plan_using_local_date_even_when_utc_date_differs(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    profile = await session.get(UserProfile, user.id)
    profile.timezone = "Asia/Yekaterinburg"
    profile.work_start = time(0)
    tomorrow = DAY + timedelta(days=1)
    task = await make_task(session, user, planned_date=tomorrow, type="routine", duration_min=30)
    owner, task_id, version = user.id, task.id, task.version
    await session.commit()
    clock = FrozenClock(at(20, 7))
    placement = TaskPlacementService(session, clock, ScheduleService(session, clock))
    response = await placement.start_now(
        owner, task_id, TaskStartNowRequest(version=version, schedule_versions={tomorrow: 0})
    )
    assert response.actual_start == clock.now() and response.planned_date == tomorrow
    async with session.begin():
        plan = (await placement.scheduler.repository.active(owner, (tomorrow,)))[tomorrow]
        assert plan.version == 1
        slot = next(saved for saved in plan.slots if saved.task_id == task_id)
        assert slot.start_at == clock.now() and slot.end_at - slot.start_at == timedelta(minutes=30)


@pytest.mark.parametrize("failure", ["storage", "calculation"])
async def test_start_failure_rolls_back_actual_time_plan_and_receipts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    owner, task, placement, events = await seed(session)
    placement.clock = placement.scheduler.clock = FrozenClock(NOW)
    before = await snapshot(session)
    if failure == "storage":
        original = placement.scheduler._save_plan

        async def fail_after_save(*args):
            await original(*args)
            raise RuntimeError("storage failure")

        monkeypatch.setattr(placement.scheduler, "_save_plan", fail_after_save)
        expected = RuntimeError
    else:

        def fail_calculation(*args):
            raise RuntimeError("calculation failure")

        monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", fail_calculation)
        expected = AppError
    with pytest.raises(expected):
        await placement.start_now(
            owner, task.id, TaskStartNowRequest(version=task.version, schedule_versions={DAY: 1})
        )
    assert not events and await snapshot(session) == before


async def test_concurrent_start_requests_have_one_winner_and_one_actual_start(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        task = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        await ScheduleService(session, CLOCK).replan(committed_owner, DAY, ScheduleTrigger.INITIAL)
        task_id, version = task.id, task.version
        await session.commit()

    async def start(offset: int):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            clock = FrozenClock(NOW + timedelta(seconds=offset))
            return await TaskPlacementService(
                session, clock, ScheduleService(session, clock)
            ).start_now(
                committed_owner,
                task_id,
                TaskStartNowRequest(version=version, schedule_versions={DAY: 1}),
            )

    results = await asyncio.wait_for(
        asyncio.gather(start(0), start(1), return_exceptions=True), timeout=15
    )
    errors = [result for result in results if isinstance(result, AppError)]
    assert len(errors) == 1 and errors[0].body.code == "TASK_VERSION_CONFLICT"
    successful = next(result for result in results if not isinstance(result, BaseException))
    async with AsyncSession(engine) as session:
        stored = await session.get(Task, task_id)
        assert stored.actual_start == successful.actual_start
        assert await ScheduleRepository(session).active_versions(committed_owner, (DAY,)) == {
            DAY: 2
        }
