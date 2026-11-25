import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleSlot, ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.placement_schemas import TaskDateLockRequest
from app.modules.tasks.placement_service import TaskPlacementService
from app.modules.users.models import User
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY
from tests.db.test_task_pin import at, command, seed
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker


def request(version: int, plan_version: int, locked: bool = True) -> TaskDateLockRequest:
    return TaskDateLockRequest(
        is_date_locked=locked, version=version, schedule_versions={DAY: plan_version}
    )


class NoClock:
    def now(self):
        raise AssertionError("An unchanged date lock must not read time")


async def test_date_lock_toggle_replans_once_and_checks_versions_before_noop(
    session: AsyncSession,
) -> None:
    owner, task, placement, events = await seed(session)
    locked = await placement.set_date_lock(owner, task.id, request(task.version, 1))
    assert locked.is_date_locked and not locked.is_pinned and locked.pinned_start is None
    assert locked.planned_date == DAY and locked.version == task.version + 1
    assert len(events) == 1 and events[0].changed_fields == {"is_date_locked"}
    before = await snapshot(session)
    placement.clock = NoClock()
    repeated = await placement.set_date_lock(owner, task.id, request(locked.version, 2))
    assert repeated == locked and await snapshot(session) == before and len(events) == 1
    await placement.scheduler.task_changed(events[0])
    assert await snapshot(session) == before
    for version, plan_version, code in (
        (task.version, 1, "TASK_VERSION_CONFLICT"),
        (locked.version, 1, "SCHEDULE_VERSION_CONFLICT"),
    ):
        with pytest.raises(AppError) as error:
            await placement.set_date_lock(owner, task.id, request(version, plan_version))
        assert error.value.body.code == code and await snapshot(session) == before
    placement.clock = CLOCK
    unlocked = await placement.set_date_lock(owner, task.id, request(locked.version, 2, False))
    assert not unlocked.is_date_locked and unlocked.version == locked.version + 1
    assert not unlocked.is_pinned and unlocked.actual_start is None and len(events) == 2
    async with session.begin():
        assert await placement.scheduler.repository.active_versions(owner, (DAY,)) == {DAY: 3}
    before = await snapshot(session)
    placement.clock = NoClock()
    assert (
        await placement.set_date_lock(owner, task.id, request(unlocked.version, 3, False))
        == unlocked
    )
    assert await snapshot(session) == before and len(events) == 2


@pytest.mark.parametrize("protection", ["pinned", "started", "past", "actual", "done", "skipped"])
async def test_date_lock_preserves_pin_actual_times_status_and_saved_history(
    session: AsyncSession, protection: str
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    clock = FrozenClock(
        at(9, 10)
        if protection == "started"
        else at(10)
        if protection in {"past", "done", "skipped"}
        else at(7, 15)
    )
    placement.clock = placement.scheduler.clock = clock
    async with session.begin():
        row = await session.get(Task, task.id)
        if protection in {"actual", "done"}:
            row.actual_start = at(7, 10)
        if protection == "done":
            row.status = TaskStatus.DONE
            row.completed_at = row.actual_end = at(7, 40)
        elif protection == "skipped":
            row.status = TaskStatus.SKIPPED
        status, actual_start, actual_end = row.status, row.actual_start, row.actual_end
        old_plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        old_plan_id = old_plan.id
        old = next(slot for slot in old_plan.slots if slot.task_id == task.id)
        interval = old.start_at, old.end_at
    locked = await placement.set_date_lock(owner, task.id, request(pinned.version, 2))
    assert locked.is_date_locked and locked.is_pinned and locked.pinned_start == pinned.pinned_start
    assert locked.status == status and locked.actual_start == actual_start
    async with session.begin():
        plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        saved = next(slot for slot in plan.slots if slot.task_id == task.id)
        assert plan.version == 3 and (saved.start_at, saved.end_at) == interval
        old = (
            await session.scalars(
                select(ScheduleSlot).where(
                    ScheduleSlot.schedule_id == old_plan_id, ScheduleSlot.task_id == task.id
                )
            )
        ).one()
        assert (old.start_at, old.end_at) == interval and old.is_pinned
        assert (await session.get(Task, task.id)).actual_end == actual_end
    assert len(events) == 2


@pytest.mark.parametrize("failure", ["save", "plan", "calculation"])
async def test_date_lock_failure_rolls_back_setting_plans_and_receipts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    owner, task, placement, events = await seed(session)
    before = await snapshot(session)
    if failure == "calculation":

        def fail_calculation(*args):
            raise RuntimeError("calculation failure")

        monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", fail_calculation)
        expected = AppError
    else:
        target = placement.repository if failure == "save" else placement.scheduler
        method = "save" if failure == "save" else "_save_plan"
        original = getattr(target, method)

        async def fail_storage(*args):
            await original(*args)
            raise RuntimeError("storage failure")

        monkeypatch.setattr(target, method, fail_storage)
        expected = RuntimeError
    with pytest.raises(expected):
        await placement.set_date_lock(owner, task.id, request(task.version, 1))
    assert not events and await snapshot(session) == before


async def test_concurrent_date_lock_and_pin_with_one_version_have_one_winner(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        task = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        await ScheduleService(session, CLOCK).replan(committed_owner, DAY, ScheduleTrigger.INITIAL)
        task_id, version, pin = task.id, task.version, command(task)
        await session.commit()

    async def change(lock: bool):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK))
            if lock:
                return await service.set_date_lock(committed_owner, task_id, request(version, 1))
            return await service.pin(committed_owner, task_id, pin)

    results = await asyncio.wait_for(
        asyncio.gather(change(True), change(False), return_exceptions=True), timeout=15
    )
    errors = [result for result in results if isinstance(result, AppError)]
    assert len(errors) == 1 and errors[0].body.code == "TASK_VERSION_CONFLICT"
    successful = next(result for result in results if not isinstance(result, BaseException))
    async with AsyncSession(engine) as session:
        stored = await session.get(Task, task_id)
        assert (stored.is_date_locked, stored.is_pinned) == (
            successful.is_date_locked,
            successful.is_pinned,
        )
        assert await ScheduleRepository(session).active_versions(committed_owner, (DAY,)) == {
            DAY: 2
        }
