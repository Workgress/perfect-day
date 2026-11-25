import asyncio
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.placement_service import TaskPlacementService
from app.modules.users.models import User
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY
from tests.db.test_task_pin import at, command, seed
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker


async def test_unpin_frees_time_preserves_date_lock_and_repeats_without_writes(
    session: AsyncSession,
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    async with session.begin():
        row = await session.get(Task, task.id)
        row.is_date_locked = True
    unpinned = await placement.unpin(owner, task.id, pinned.version, 2)
    assert unpinned.is_pinned is False and unpinned.pinned_start is None
    assert unpinned.is_date_locked is True and unpinned.actual_start is None
    assert unpinned.planned_date == DAY and unpinned.version == pinned.version + 1
    assert len(events) == 2 and events[-1].changed_fields == {"is_pinned", "pinned_start"}
    async with session.begin():
        plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        slot = next(slot for slot in plan.slots if slot.task_id == task.id)
        assert plan.version == 3 and slot.is_pinned is False
        assert slot.start_at != pinned.pinned_start and slot.start_at.minute % 15 == 0
    before = await snapshot(session)
    repeated = await placement.unpin(owner, task.id, unpinned.version, 3)
    assert repeated == unpinned and await snapshot(session) == before and len(events) == 2
    await placement.scheduler.task_changed(events[-1])
    assert await snapshot(session) == before
    for version, schedule_version, code in (
        (pinned.version, 2, "TASK_VERSION_CONFLICT"),
        (unpinned.version, 2, "SCHEDULE_VERSION_CONFLICT"),
    ):
        with pytest.raises(AppError) as error:
            await placement.unpin(owner, task.id, version, schedule_version)
        assert error.value.body.code == code and await snapshot(session) == before


async def test_already_unpinned_task_is_a_noop(session: AsyncSession) -> None:
    owner, task, placement, events = await seed(session)
    before = await snapshot(session)
    assert await placement.unpin(owner, task.id, task.version, 1) == task
    assert not events and await snapshot(session) == before


@pytest.mark.parametrize("protection", ["started", "past", "actual", "done", "skipped"])
async def test_unpin_keeps_protected_interval_status_and_actual_times(
    session: AsyncSession, protection: str
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    clock = FrozenClock(
        at(7, 15) if protection == "actual" else at(9, 10) if protection == "started" else at(10)
    )
    placement.clock = placement.scheduler.clock = clock
    async with session.begin():
        row = await session.get(Task, task.id)
        row.is_date_locked = True
        if protection in {"actual", "done"}:
            row.actual_start = at(7, 10) if protection == "actual" else at(9, 8)
        if protection == "done":
            row.status = TaskStatus.DONE
            row.completed_at = at(9, 35)
            row.actual_end = at(9, 35)
        elif protection == "skipped":
            row.status = TaskStatus.SKIPPED
        status, actual_start, actual_end = row.status, row.actual_start, row.actual_end
        plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        old = next(slot for slot in plan.slots if slot.task_id == task.id)
        interval = old.start_at, old.end_at
    unpinned = await placement.unpin(owner, task.id, pinned.version, 2)
    assert not unpinned.is_pinned and unpinned.pinned_start is None
    assert (
        unpinned.is_date_locked
        and unpinned.actual_start == actual_start
        and unpinned.status == status
    )
    async with session.begin():
        plan = (await placement.scheduler.repository.active(owner, (DAY,)))[DAY]
        saved = next(slot for slot in plan.slots if slot.task_id == task.id)
        assert (saved.start_at, saved.end_at) == interval and not saved.is_pinned
        stored = await session.get(Task, task.id)
        assert stored.actual_end == actual_end and plan.version == 3
    assert len(events) == 2


@pytest.mark.parametrize("failure", ["save", "plan", "calculation"])
async def test_unpin_rolls_back_task_plan_receipts_and_event_on_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    owner, task, placement, events = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    before = await snapshot(session)
    if failure == "calculation":

        def fail_calculation(*args):
            raise RuntimeError("calculation failure")

        monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", fail_calculation)
        expected = AppError
    else:
        original = (
            placement.repository.save if failure == "save" else placement.scheduler._save_plan
        )

        async def fail_storage(*args):
            await original(*args)
            raise RuntimeError("storage failure")

        target = placement.repository if failure == "save" else placement.scheduler
        monkeypatch.setattr(target, "save" if failure == "save" else "_save_plan", fail_storage)
        expected = RuntimeError
    with pytest.raises(expected):
        await placement.unpin(owner, task.id, pinned.version, 2)
    assert len(events) == 1 and await snapshot(session) == before


async def test_unpin_normalizes_a_leftover_start_without_pin_flag(session: AsyncSession) -> None:
    owner, task, placement, _ = await seed(session)
    pinned = await placement.pin(owner, task.id, command(task))
    async with session.begin():
        row = await session.get(Task, task.id)
        row.is_pinned = False
    result = await placement.unpin(owner, task.id, pinned.version, 2)
    assert result.is_pinned is False and result.pinned_start is None
    assert result.version == pinned.version + 1


async def test_concurrent_unpin_and_repin_of_one_version_have_one_winner(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        task = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        await ScheduleService(session, CLOCK).replan(committed_owner, DAY, ScheduleTrigger.INITIAL)
        request, task_id = command(task), task.id
        await session.commit()
        pinned = await TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK)).pin(
            committed_owner, task_id, request
        )

    async def change(unpin: bool):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK))
            if unpin:
                return await service.unpin(committed_owner, task_id, pinned.version, 2)
            return await service.pin(
                committed_owner, task_id, command(pinned, start=at(10), versions={DAY: 2})
            )

    results = await asyncio.wait_for(
        asyncio.gather(change(True), change(False), return_exceptions=True), timeout=15
    )
    errors = [result for result in results if isinstance(result, AppError)]
    assert len(errors) == 1 and errors[0].body.code == "TASK_VERSION_CONFLICT"
    assert len([result for result in results if not isinstance(result, BaseException)]) == 1
    async with AsyncSession(engine) as session:
        assert await ScheduleRepository(session).active_versions(committed_owner, (DAY,)) == {
            DAY: 3
        }
