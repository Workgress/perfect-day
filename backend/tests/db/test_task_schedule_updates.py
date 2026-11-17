import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.schedule.models import (
    Schedule,
    ScheduleSlot,
    ScheduleTrigger,
    SlotKind,
    TaskReplanReceipt,
)
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.events import TaskChanged
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskPatch
from app.modules.tasks.service import TaskService, TaskVersionConflictError
from app.modules.users.models import User
from tests.db.test_schedule_service import CLOCK, DAY, setup_user

pytestmark = pytest.mark.docker
TARGET = DAY + timedelta(days=1)


async def service(session: AsyncSession, *, completed: bool = True) -> tuple[UUID, TaskService]:
    user = await setup_user(session, completed=completed)
    user_id = user.id
    await session.commit()
    scheduler = ScheduleService(session, CLOCK)
    return user_id, TaskService(session, CLOCK, coordinator=scheduler)


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


async def snapshot(session: AsyncSession) -> list[list[Any]]:
    async with session.begin():
        return [
            list(
                (
                    await session.execute(
                        select(model.__table__).order_by(*model.__table__.primary_key.columns)
                    )
                ).mappings()
            )
            for model in (Task, Schedule, ScheduleSlot, TaskReplanReceipt)
        ]


@pytest.mark.parametrize("operation", ["create", "patch", "delete", "complete", "skip"])
async def test_planner_write_failure_rolls_back_task_slots_versions_and_receipt(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    scheduler = ScheduleService(session, CLOCK)
    tasks.coordinator = scheduler
    observed: list[TaskChanged] = []

    async def notify(event: TaskChanged) -> None:
        observed.append(event)

    tasks.on_changed = notify
    before = await snapshot(session)
    save = scheduler._save_plan

    async def fail_after_save(*args: Any, **kwargs: Any) -> None:
        await save(*args, **kwargs)
        raise RuntimeError("storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(scheduler, "_save_plan", fail_after_save)
        with pytest.raises(RuntimeError, match="storage failure"):
            if operation == "create":
                await tasks.create(user_id, body())
            elif operation == "patch":
                await tasks.patch(
                    user_id, created.id, TaskPatch(version=created.version, duration_min=40)
                )
            elif operation == "delete":
                await tasks.delete(user_id, created.id, created.version)
            elif operation == "complete":
                await tasks.complete(user_id, created.id, created.version)
            else:
                await tasks.skip(user_id, created.id, created.version)
    assert not session.in_transaction()
    assert await snapshot(session) == before
    assert observed == []
    changed = await tasks.patch(
        user_id, created.id, TaskPatch(version=created.version, duration_min=40)
    )
    assert changed.duration_min == 40 and len(observed) == 1


async def test_failure_on_second_date_rolls_back_first_date_and_move(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    scheduler = ScheduleService(session, CLOCK)
    tasks.coordinator = scheduler
    replan = scheduler.replan
    visited = []

    async def fail_second(*args: Any, **kwargs: Any) -> Any:
        visited.append(args[1])
        if len(visited) == 2:
            raise RuntimeError("second date failure")
        return await replan(*args, **kwargs)

    before = await snapshot(session)
    monkeypatch.setattr(scheduler, "replan", fail_second)
    with pytest.raises(RuntimeError, match="second date failure"):
        await tasks.patch(
            user_id,
            created.id,
            TaskPatch(version=created.version, planned_date=TARGET + timedelta(days=1)),
        )
    assert visited == [TARGET, TARGET + timedelta(days=1)]
    assert await snapshot(session) == before


async def test_replayed_and_stale_events_do_not_create_extra_versions(
    session: AsyncSession,
) -> None:
    user_id, tasks = await service(session)
    created = await tasks.create(user_id, body())
    change = TaskChanged(
        user_id,
        created.id,
        "updated",
        frozenset({"priority"}),
        TARGET,
        TARGET,
        created.version,
        CLOCK.now(),
    )
    await ScheduleService(session, CLOCK).task_changed(change)
    before = await snapshot(session)
    await ScheduleService(session, CLOCK).task_changed(change)
    assert await snapshot(session) == before
    changed = await tasks.patch(
        user_id, created.id, TaskPatch(version=created.version, priority="high")
    )
    before = await snapshot(session)
    await ScheduleService(session, CLOCK).task_changed(change)
    assert await snapshot(session) == before
    assert changed.version > created.version


@pytest.fixture
async def committed_owner(engine: AsyncEngine) -> AsyncIterator[UUID]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await setup_user(session, completed=True)
        user_id = user.id
        await session.commit()
    try:
        yield user_id
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))


async def test_competing_writes_use_owner_lock_and_reject_stale_version(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
        created = await tasks.create(committed_owner, body())

    async def change(duration: int) -> Any:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
            return await tasks.patch(
                committed_owner,
                created.id,
                TaskPatch(version=created.version, duration_min=duration),
            )

    results = await asyncio.wait_for(
        asyncio.gather(change(40), change(50), return_exceptions=True), timeout=15
    )
    assert sum(isinstance(item, TaskVersionConflictError) for item in results) == 1
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    async with AsyncSession(engine, expire_on_commit=False) as session:
        plans = await active(session, committed_owner)
        assert len(plans) == 1 and plans[0].version == 2
        async with session.begin():
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskReplanReceipt)
                    .where(TaskReplanReceipt.user_id == committed_owner)
                )
                == 2
            )


async def test_concurrent_event_replays_are_processed_once(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
        created = await tasks.create(committed_owner, body())
    change = TaskChanged(
        committed_owner,
        created.id,
        "updated",
        frozenset({"priority"}),
        TARGET,
        TARGET,
        created.version,
        CLOCK.now(),
    )

    async def deliver() -> None:
        async with AsyncSession(engine) as session:
            await ScheduleService(session, CLOCK).task_changed(change)

    await asyncio.wait_for(asyncio.gather(deliver(), deliver()), timeout=15)
    await deliver()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        plans = await active(session, committed_owner)
        assert len(plans) == 1 and plans[0].version == 2


async def test_opposite_date_moves_do_not_deadlock_or_duplicate_tasks(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    other_day = TARGET + timedelta(days=1)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
        first = await tasks.create(committed_owner, body())
        second = await tasks.create(
            committed_owner, body().model_copy(update={"planned_date": other_day})
        )

    async def move(task_id: UUID, version: int, target: Any) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tasks = TaskService(session, CLOCK, coordinator=ScheduleService(session, CLOCK))
            await tasks.patch(
                committed_owner, task_id, TaskPatch(version=version, planned_date=target)
            )

    await asyncio.wait_for(
        asyncio.gather(
            move(first.id, first.version, other_day), move(second.id, second.version, TARGET)
        ),
        timeout=15,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        plans = await active(session, committed_owner)
        assert [plan.date for plan in plans] == [TARGET, other_day]
        async with session.begin():
            placements = list(
                await session.execute(
                    select(Schedule.date, ScheduleSlot.task_id)
                    .join(ScheduleSlot, ScheduleSlot.schedule_id == Schedule.id)
                    .where(
                        Schedule.user_id == committed_owner,
                        Schedule.is_active.is_(True),
                        ScheduleSlot.kind == SlotKind.TASK,
                    )
                )
            )
            assert set(placements) == {(TARGET, second.id), (other_day, first.id)}
            assert len(placements) == 2


async def test_foreign_task_event_cannot_change_schedules(session: AsyncSession) -> None:
    owner_id, tasks = await service(session)
    created = await tasks.create(owner_id, body())
    async with session.begin():
        other = await setup_user(session, completed=True)
        other_id = other.id
    before = await snapshot(session)
    change = TaskChanged(
        other_id,
        created.id,
        "deleted",
        frozenset({"deleted_at"}),
        TARGET,
        None,
        created.version,
        CLOCK.now(),
    )
    await ScheduleService(session, CLOCK).task_changed(change)
    assert await snapshot(session) == before
