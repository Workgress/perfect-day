import asyncio
from datetime import UTC, datetime, timedelta
from itertools import permutations
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.events import TaskChanged
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskPatch
from app.modules.tasks.service import TaskService, TaskVersionConflictError
from app.modules.users.models import User
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker
TARGET = DAY + timedelta(days=1)


def at(hour: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=UTC)


async def change_state(
    session: AsyncSession, user_id: UUID, task_id: UUID, version: int, **values: Any
) -> TaskChanged:
    scheduler = ScheduleService(session, CLOCK)
    async with session.begin(), scheduler.mutation(user_id):
        row = await TaskRepository(session).get(user_id, task_id, for_update=True)
        assert row is not None
        if row.version != version:
            raise TaskVersionConflictError()
        for field, value in values.items():
            setattr(row, field, value)
        row.version += 1
        row.updated_at = CLOCK.now()
        await session.flush()
        event = TaskChanged(
            user_id,
            task_id,
            "updated",
            frozenset(values),
            row.planned_date,
            row.planned_date,
            row.version,
            CLOCK.now(),
        )
        await scheduler.task_changed(event)
    return event


async def details(session: AsyncSession, user_id: UUID, day=DAY):
    async with session.begin():
        result = await ScheduleReader(session).get_details(user_id, day)
        assert result is not None
        return result


async def test_pin_move_unpin_start_replan_and_replayed_events_keep_a_consistent_schedule(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    await session.commit()
    scheduler = ScheduleService(session, CLOCK)
    tasks = TaskService(session, CLOCK, coordinator=scheduler)
    first = await tasks.create(
        user_id, TaskCreate(title="Protected", type="routine", duration_min=30, planned_date=DAY)
    )
    pin = await change_state(
        session, user_id, first.id, first.version, is_pinned=True, pinned_start=at(14)
    )
    pinned = (await details(session, user_id)).placement_explanations[0]
    assert pinned.preservation == "pinned" and pinned.start_at == at(14)
    other = await tasks.create(
        user_id, TaskCreate(title="Movable", type="routine", duration_min=30, planned_date=DAY)
    )
    moved = await tasks.patch(
        user_id, other.id, TaskPatch(version=other.version, planned_date=TARGET)
    )
    assert moved.planned_date == TARGET
    source = await details(session, user_id)
    assert source.placement_explanations[0].start_at == pinned.start_at
    before = await snapshot(session)
    await scheduler.task_changed(pin)
    assert await snapshot(session) == before
    current = await tasks.get(user_id, first.id)
    await change_state(
        session, user_id, first.id, current.version, is_pinned=False, pinned_start=None
    )
    unpinned = (await details(session, user_id)).placement_explanations[0]
    current = await tasks.get(user_id, first.id)
    start = await change_state(
        session, user_id, first.id, current.version, actual_start=CLOCK.now()
    )
    started = (await details(session, user_id)).placement_explanations[0]
    assert started.preservation == "started"
    assert (started.start_at, started.end_at) == (unpinned.start_at, unpinned.end_at)
    assert started.reason_codes == ("TASK_STARTED",)
    before = await snapshot(session)
    await scheduler.task_changed(start)
    assert await snapshot(session) == before
    current = await tasks.get(user_id, first.id)
    with pytest.raises(AppError) as error:
        await tasks.patch(
            user_id, first.id, TaskPatch(version=current.version, planned_date=TARGET)
        )
    assert error.value.body.code == "CONFLICT"
    assert await snapshot(session) == before
    moved = await tasks.patch(user_id, other.id, TaskPatch(version=moved.version, planned_date=DAY))
    async with session.begin():
        await scheduler.replan(user_id, DAY, ScheduleTrigger.MANUAL_EDIT)
    source = await details(session, user_id)
    by_id = {item.task_id: item for item in source.placement_explanations}
    assert set(by_id) == {first.id, other.id}
    assert (by_id[first.id].start_at, by_id[first.id].end_at) == (started.start_at, started.end_at)
    assert (
        by_id[first.id].end_at <= by_id[other.id].start_at
        or by_id[other.id].end_at <= by_id[first.id].start_at
    )
    assert not (await details(session, user_id, TARGET)).placement_explanations


@pytest.mark.parametrize("operation", ["pin", "start", "transfer"])
async def test_state_changes_and_transfer_roll_back_tasks_plans_and_receipts_on_failure(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    await session.commit()
    task = await TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK)).create(
        user_id, TaskCreate(title="Protected", type="routine", duration_min=30, planned_date=DAY)
    )
    if operation == "transfer":
        await change_state(
            session, user_id, task.id, task.version, is_pinned=True, pinned_start=at(14)
        )
        task = await TaskService(
            session, CLOCK, coordinator=ScheduleService(session, CLOCK)
        ).create(
            user_id, TaskCreate(title="Movable", type="routine", duration_min=30, planned_date=DAY)
        )
    before = await snapshot(session)
    original = ScheduleService._save_plan

    async def fail_after_save(self, *args):
        saved = await original(self, *args)
        if operation != "transfer" or args[1].day == TARGET:
            raise RuntimeError("injected storage failure")
        return saved

    with monkeypatch.context() as patch:
        patch.setattr(ScheduleService, "_save_plan", fail_after_save)
        with pytest.raises(RuntimeError, match="injected storage failure"):
            if operation == "transfer":
                await TaskService(
                    session, CLOCK, coordinator=ScheduleService(session, CLOCK)
                ).patch(user_id, task.id, TaskPatch(version=task.version, planned_date=TARGET))
            else:
                await change_state(
                    session,
                    user_id,
                    task.id,
                    task.version,
                    **(
                        {"is_pinned": True, "pinned_start": at(14)}
                        if operation == "pin"
                        else {"actual_start": CLOCK.now()}
                    ),
                )
    assert await snapshot(session) == before


@pytest.mark.parametrize("order", [None, *permutations(("start", "transfer", "replan"))])
async def test_start_transfer_and_replan_preserve_intervals_in_every_order(
    engine: AsyncEngine,
    committed_owner: UUID,
    order: tuple[str, ...] | None,
) -> None:
    owner = committed_owner
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        user = await session.get(User, owner)
        assert user is not None
        pinned = await make_task(
            session,
            user,
            planned_date=DAY,
            type="routine",
            duration_min=30,
            is_pinned=True,
            pinned_start=at(14),
        )
        starting = await make_task(
            session,
            user,
            planned_date=DAY,
            type="routine",
            duration_min=30,
            is_pinned=True,
            pinned_start=at(15),
        )
        movable = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        initial = await ScheduleService(session, CLOCK).replan(owner, DAY, ScheduleTrigger.INITIAL)
        protected = {
            slot.task.task_id: slot.interval
            for slot in initial.plan.slots
            if slot.task is not None and slot.task.task_id in {pinned.id, starting.id}
        }
        starting_id, starting_version = starting.id, starting.version
        movable_id, movable_version = movable.id, movable.version
    barrier = asyncio.Barrier(3) if order is None else None

    async def begin_task():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if barrier is not None:
                await barrier.wait()
            return await change_state(
                session, owner, starting_id, starting_version, actual_start=CLOCK.now()
            )

    async def transfer():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if barrier is not None:
                await barrier.wait()
            return await TaskService(
                session, CLOCK, coordinator=ScheduleService(session, CLOCK)
            ).patch(owner, movable_id, TaskPatch(version=movable_version, planned_date=TARGET))

    async def replan():
        async with AsyncSession(engine) as session:
            if barrier is not None:
                await barrier.wait()
            async with session.begin():
                return await ScheduleService(session, CLOCK).replan(
                    owner, DAY, ScheduleTrigger.MANUAL_EDIT
                )

    if order is None:
        start, _, _ = await asyncio.wait_for(
            asyncio.gather(begin_task(), transfer(), replan()), timeout=15
        )
    else:
        operations = {"start": begin_task, "transfer": transfer, "replan": replan}
        outcomes = [await operations[name]() for name in order]
        start = outcomes[order.index("start")]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = await details(session, owner)
        target = await details(session, owner, TARGET)
        by_id = {item.task_id: item for item in source.placement_explanations}
        assert set(by_id) == set(protected)
        for task_id, interval in protected.items():
            assert (by_id[task_id].start_at, by_id[task_id].end_at) == (
                interval.start,
                interval.end,
            )
        assert by_id[starting_id].preservation == "started"
        assert [item.task_id for item in target.placement_explanations] == [movable_id]
        async with session.begin():
            versions = list(
                await session.scalars(
                    select(Schedule.version)
                    .where(Schedule.user_id == owner, Schedule.date == DAY)
                    .order_by(Schedule.version)
                )
            )
        assert versions == [1, 2, 3, 4]
        before = await snapshot(session)
        await ScheduleService(session, CLOCK).task_changed(start)
        assert await snapshot(session) == before


async def test_concurrent_start_and_transfer_of_one_version_have_one_winner(
    engine: AsyncEngine,
    committed_owner: UUID,
) -> None:
    owner = committed_owner
    async with AsyncSession(engine, expire_on_commit=False) as session:
        created = await TaskService(
            session, CLOCK, coordinator=ScheduleService(session, CLOCK)
        ).create(
            owner,
            TaskCreate(
                title="Competing operations", type="routine", duration_min=30, planned_date=DAY
            ),
        )
        original = (await details(session, owner)).placement_explanations[0]
    barrier = asyncio.Barrier(2)

    async def start():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await barrier.wait()
            return await change_state(
                session, owner, created.id, created.version, actual_start=CLOCK.now()
            )

    async def transfer():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await barrier.wait()
            return await TaskService(
                session, CLOCK, coordinator=ScheduleService(session, CLOCK)
            ).patch(owner, created.id, TaskPatch(version=created.version, planned_date=TARGET))

    results = await asyncio.wait_for(
        asyncio.gather(start(), transfer(), return_exceptions=True), timeout=15
    )
    assert sum(isinstance(item, TaskVersionConflictError) for item in results) == 1
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    async with AsyncSession(engine) as session, session.begin():
        task = await TaskRepository(session).get(owner, created.id)
        assert task is not None and task.status == "scheduled"
        placements = list(
            await session.execute(
                select(Schedule.date, ScheduleSlot.start_at, ScheduleSlot.end_at)
                .join(ScheduleSlot, ScheduleSlot.schedule_id == Schedule.id)
                .where(
                    Schedule.user_id == owner,
                    Schedule.is_active.is_(True),
                    ScheduleSlot.task_id == created.id,
                )
            )
        )
        assert len(placements) == 1 and placements[0].date == task.planned_date
        if task.actual_start is not None:
            assert task.actual_start == CLOCK.now() and task.planned_date == DAY
            assert (placements[0].start_at, placements[0].end_at) == (
                original.start_at,
                original.end_at,
            )
        else:
            assert task.planned_date == TARGET
