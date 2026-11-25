import asyncio
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.errors import TaskVersionConflictError
from app.modules.tasks.models import Task
from app.modules.users.models import User
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user
from tests.db.test_task_schedule_updates import committed_owner as committed_owner

pytestmark = pytest.mark.docker
TARGET = DAY + timedelta(days=1)


async def seed(session: AsyncSession) -> tuple[UUID, UUID, int]:
    user = await setup_user(session, completed=True)
    task = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    await ScheduleService(session, CLOCK).replan(user.id, DAY, ScheduleTrigger.INITIAL)
    result = user.id, task.id, task.version
    await session.commit()
    return result


async def test_task_guard_checks_both_dates_and_rolls_back_task_and_plans(
    session: AsyncSession,
) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    async with session.begin():
        with pytest.raises(RuntimeError, match="second day failed"):
            async with scheduler.task_mutation(
                owner, task_id, version, {DAY: 1, TARGET: 0}, target_date=TARGET
            ) as task:
                task.planned_date = TARGET
                task.version += 1
                await session.flush()
                await scheduler.replan(owner, DAY, ScheduleTrigger.MANUAL_EDIT)
                await scheduler.replan(owner, TARGET, ScheduleTrigger.MANUAL_EDIT)
                raise RuntimeError("second day failed")
        stored = await session.get(Task, task_id, populate_existing=True)
        assert stored is not None and stored.planned_date == DAY and stored.version == version
        assert await scheduler.repository.active_versions(owner, (DAY, TARGET)) == {DAY: 1}
        assert len(list(await session.scalars(select(Schedule)))) == 1


@pytest.mark.parametrize("day", [DAY, TARGET])
async def test_task_guard_rejects_stale_source_or_target_before_yielding(
    session: AsyncSession, day: date
) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    expected = {DAY: 1, TARGET: 0}
    expected[day] = 2
    with pytest.raises(AppError) as error:
        async with (
            session.begin(),
            scheduler.task_mutation(owner, task_id, version, expected, target_date=TARGET),
        ):
            pytest.fail("A stale plan must be rejected before mutation")
    assert error.value.body.code == "SCHEDULE_VERSION_CONFLICT"
    assert error.value.body.details == {
        "planned_date": day.isoformat(),
        "expected_version": 2,
        "current_version": 1 if day == DAY else 0,
    }


@pytest.mark.parametrize(
    "dates", [{}, {DAY: 1}, {TARGET: 0}, {DAY: 1, TARGET: 0, DAY - timedelta(days=1): 0}]
)
async def test_task_guard_requires_exact_source_and_target_dates(
    session: AsyncSession, dates: dict[date, int]
) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    with pytest.raises(AppError) as error:
        async with (
            session.begin(),
            scheduler.task_mutation(owner, task_id, version, dates, target_date=TARGET),
        ):
            pytest.fail("Invalid dates must be rejected before mutation")
    assert error.value.status_code == 422
    assert error.value.body.details["fields"][0]["field"] == "body.schedule_versions"


async def test_task_version_precedes_plan_checks_even_for_noop(session: AsyncSession) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    with pytest.raises(TaskVersionConflictError) as error:
        async with session.begin(), scheduler.task_mutation(owner, task_id, version - 1, {}):
            pytest.fail("A stale task must be rejected before mutation")
    assert error.value.body.details == {
        "expected_version": version - 1,
        "current_version": version,
    }


@pytest.mark.parametrize("visibility", ["foreign", "deleted", "missing"])
async def test_task_guard_hides_unavailable_tasks_before_version_checks(
    session: AsyncSession, visibility: str
) -> None:
    owner, task_id, _ = await seed(session)
    if visibility == "foreign":
        other = await setup_user(session, completed=True)
        owner = other.id
        await session.commit()
    elif visibility == "deleted":
        task = await session.get(Task, task_id)
        assert task is not None
        task.deleted_at = CLOCK.now()
        await session.commit()
    else:
        task_id = uuid4()
    with pytest.raises(AppError) as error:
        async with (
            session.begin(),
            ScheduleService(session, CLOCK).task_mutation(owner, task_id, 999, {}),
        ):
            pytest.fail("An unavailable task must never be yielded")
    assert error.value.status_code == 404
    assert error.value.body.code == "TASK_NOT_FOUND" and error.value.body.details == {}


async def test_zero_version_detects_a_plan_created_since_reading(session: AsyncSession) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(owner, TARGET, ScheduleTrigger.INITIAL)
    await session.commit()
    with pytest.raises(AppError) as error:
        async with (
            session.begin(),
            scheduler.task_mutation(
                owner, task_id, version, {DAY: 1, TARGET: 0}, target_date=TARGET
            ),
        ):
            pytest.fail("A newly created target plan must invalidate expected absence")
    assert error.value.body.details == {
        "planned_date": TARGET.isoformat(),
        "expected_version": 0,
        "current_version": 1,
    }


@pytest.mark.parametrize("expected", [1, {DAY: 1}])
async def test_same_day_guard_accepts_one_version_without_writes(
    session: AsyncSession, expected: int | dict[date, int]
) -> None:
    owner, task_id, version = await seed(session)
    scheduler = ScheduleService(session, CLOCK)
    async with session.begin():
        async with scheduler.task_mutation(
            owner, task_id, version, expected, target_date=DAY
        ) as task:
            assert task.id == task_id and task.is_date_locked is False
        assert await scheduler.repository.active_versions(owner, (DAY,)) == {DAY: 1}
        await session.refresh(task)
        assert task.version == version


async def test_single_schedule_version_is_checked_for_current_task_day(
    session: AsyncSession,
) -> None:
    owner, task_id, version = await seed(session)
    with pytest.raises(AppError) as error:
        async with (
            session.begin(),
            ScheduleService(session, CLOCK).task_mutation(owner, task_id, version, 0),
        ):
            pytest.fail("An obsolete query version must be rejected before mutation")
    assert error.value.body.code == "SCHEDULE_VERSION_CONFLICT"
    assert error.value.body.details == {
        "planned_date": DAY.isoformat(),
        "expected_version": 0,
        "current_version": 1,
    }


@pytest.mark.parametrize("same_task", [False, True])
async def test_concurrent_commands_with_same_versions_have_one_winner(
    engine: AsyncEngine, committed_owner: UUID, same_task: bool
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        assert user is not None
        first = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        second = (
            first
            if same_task
            else await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        )
        await ScheduleService(session, CLOCK).replan(committed_owner, DAY, ScheduleTrigger.INITIAL)
        inputs = [(first.id, first.version), (second.id, second.version)]
        await session.commit()
    ready = asyncio.Event()

    async def change(task_id: UUID, version: int) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            await ready.wait()
            scheduler = ScheduleService(session, CLOCK)
            async with scheduler.task_mutation(committed_owner, task_id, version, {DAY: 1}) as task:
                task.title = "Изменённая задача"
                task.version += 1
                await session.flush()
                await scheduler.replan(committed_owner, DAY, ScheduleTrigger.MANUAL_EDIT)

    requests = [asyncio.create_task(change(*item)) for item in inputs]
    ready.set()
    results = await asyncio.wait_for(asyncio.gather(*requests, return_exceptions=True), timeout=15)
    failures = [item for item in results if isinstance(item, AppError)]
    assert len(failures) == 1 and sum(item is None for item in results) == 1
    assert failures[0].body.code == (
        "TASK_VERSION_CONFLICT" if same_task else "SCHEDULE_VERSION_CONFLICT"
    )
    async with AsyncSession(engine) as session:
        assert await ScheduleRepository(session).active_versions(committed_owner, (DAY,)) == {
            DAY: 2
        }
        plans = list(
            await session.scalars(select(Schedule).where(Schedule.user_id == committed_owner))
        )
        assert len(plans) == 2 and sum(plan.is_active for plan in plans) == 1
