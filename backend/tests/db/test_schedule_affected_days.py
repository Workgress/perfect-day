from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock, local_to_utc, parse_timezone
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskPatch
from app.modules.tasks.service import TaskService
from app.modules.users.models import UserProfile
from tests.db.factories import make_schedule, make_slot, make_task
from tests.db.test_schedule_service import DAY, setup_user

pytestmark = pytest.mark.docker


def at(day: date, hour: int, minute: int, zone: str) -> datetime:
    return local_to_utc(datetime.combine(day, time(hour, minute)), parse_timezone(zone))


async def scenario(session: AsyncSession, zone: str, *, day: date = DAY) -> tuple[Any, TaskService]:
    user = await setup_user(session, completed=True)
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.timezone = zone
    profile.birth_date = day - timedelta(days=2)
    profile.birth_time = time(12)
    profile.birth_tz = zone
    profile.birth_at_utc = at(day - timedelta(days=2), 12, 0, zone)
    profile.work_start, profile.work_end, profile.sleep_time = time(8), time(18), time(23)
    clock = FrozenClock(at(day, 10, 15, zone))
    await session.commit()
    return user, TaskService(session, clock, coordinator=ScheduleService(session, clock))


async def placements(session: AsyncSession, user_id: Any) -> dict[Any, tuple[datetime, datetime]]:
    async with session.begin():
        rows = await session.execute(
            select(ScheduleSlot.task_id, ScheduleSlot.start_at, ScheduleSlot.end_at)
            .join(Schedule)
            .where(
                Schedule.user_id == user_id,
                Schedule.is_active.is_(True),
                ScheduleSlot.task_id.is_not(None),
            )
        )
        return {task_id: (start, end) for task_id, start, end in rows}


@pytest.mark.parametrize(
    ("zone", "day"),
    [("UTC", DAY), ("Asia/Yekaterinburg", DAY), ("Europe/Berlin", date(2026, 10, 25))],
)
async def test_current_day_keeps_past_started_completed_and_pinned_slots(
    session: AsyncSession, zone: str, day: date
) -> None:
    user, tasks = await scenario(session, zone, day=day)
    protected = {}
    async with session.begin():
        plan = await make_schedule(session, user, date=day)
        for hour, status, pinned in [
            (8, TaskStatus.SCHEDULED, False),
            (9, TaskStatus.DONE, False),
            (10, TaskStatus.SCHEDULED, False),
            (14, TaskStatus.SCHEDULED, True),
            (16, TaskStatus.DONE, False),
        ]:
            start = at(day, hour, 0, zone)
            row = await make_task(
                session,
                user,
                type="routine",
                duration_min=30,
                planned_date=day,
                status=status,
                completed_at=start + timedelta(minutes=30) if status == TaskStatus.DONE else None,
                is_pinned=pinned,
                pinned_start=start if pinned else None,
            )
            await make_slot(
                session,
                plan,
                row,
                start_at=start,
                end_at=start + timedelta(minutes=30),
                is_pinned=pinned,
            )
            protected[row.id] = (start, start + timedelta(minutes=30))
    added = await tasks.create(
        user.id, TaskCreate(title="Added", type="routine", duration_min=15, planned_date=day)
    )
    saved = await placements(session, user.id)
    assert {key: saved[key] for key in protected} == protected
    assert saved[added.id][0] >= tasks.clock.now()
    assert all(
        saved[added.id][1] <= start or saved[added.id][0] >= end
        for start, end in protected.values()
    )


@pytest.mark.parametrize("hour", [8, 9, 10, 14, 16])
@pytest.mark.parametrize("field", ["duration_min", "planned_date"])
async def test_changes_that_invalidate_history_or_pins_are_rolled_back(
    session: AsyncSession, hour: int, field: str
) -> None:
    zone = "UTC"
    user, tasks = await scenario(session, zone)
    user_id = user.id
    async with session.begin():
        start = at(DAY, hour, 0, zone)
        row = await make_task(
            session,
            user,
            type="routine",
            duration_min=30,
            planned_date=DAY,
            status=TaskStatus.DONE if hour in {9, 16} else TaskStatus.SCHEDULED,
            completed_at=start if hour in {9, 16} else None,
            is_pinned=hour == 14,
            pinned_start=start if hour == 14 else None,
        )
        task_id = row.id
        plan = await make_schedule(session, user, date=DAY)
        await make_slot(
            session,
            plan,
            row,
            start_at=start,
            end_at=start + timedelta(minutes=30),
            is_pinned=hour == 14,
        )
    values = {field: 45 if field == "duration_min" else DAY + timedelta(days=1)}
    with pytest.raises(AppError) as error:
        await tasks.patch(user.id, task_id, TaskPatch(version=1, **values))
    assert error.value.body.code in {"CONFLICT", "TASK_PINNED"}
    unchanged = await tasks.get(user_id, task_id)
    assert unchanged.version == 1 and unchanged.duration_min == 30 and unchanged.planned_date == DAY
    assert (await placements(session, user_id))[task_id] == (start, start + timedelta(minutes=30))


@pytest.mark.parametrize("operation", ["delete", "skip"])
async def test_removing_future_work_frees_capacity_for_pending_task(
    session: AsyncSession, operation: str
) -> None:
    user, tasks = await scenario(session, "UTC")
    async with session.begin():
        profile = await session.get(UserProfile, user.id)
        assert profile is not None
        profile.work_end = time(9)
        profile.lunch_duration_min = 0
    target = DAY + timedelta(days=1)
    first = await tasks.create(
        user.id,
        TaskCreate(
            title="First", type="routine", duration_min=60, planned_date=target, priority="high"
        ),
    )
    waiting = await tasks.create(
        user.id,
        TaskCreate(
            title="Waiting", type="routine", duration_min=30, planned_date=target, priority="low"
        ),
    )
    assert waiting.status == TaskStatus.PENDING
    current = await tasks.get(user.id, first.id)
    if operation == "delete":
        await tasks.delete(user.id, first.id, current.version)
    else:
        await tasks.skip(user.id, first.id, current.version)
    assert (await tasks.get(user.id, waiting.id)).status == TaskStatus.SCHEDULED
    saved = await placements(session, user.id)
    assert set(saved) == {waiting.id}
    assert saved[waiting.id][0] == at(target, 8, 0, "UTC")


@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Berlin"])
async def test_precise_deadline_is_used_by_task_driven_replanning(
    session: AsyncSession, zone: str
) -> None:
    user, tasks = await scenario(session, zone)
    target = DAY + timedelta(days=1)
    due = at(target, 8, 30, zone)
    created = await tasks.create(
        user.id,
        TaskCreate(title="Due", type="routine", duration_min=30, planned_date=target, deadline=due),
    )
    saved = await placements(session, user.id)
    assert saved[created.id] == (at(target, 8, 0, zone), due)
    shortened = await tasks.patch(
        user.id, created.id, TaskPatch(version=created.version, deadline=due - timedelta(minutes=1))
    )
    assert shortened.status == TaskStatus.PENDING
    assert created.id not in await placements(session, user.id)


async def test_next_local_day_can_start_before_current_utc_date_ends(session: AsyncSession) -> None:
    user, tasks = await scenario(session, "Asia/Yekaterinburg")
    tasks.clock = FrozenClock(datetime(2026, 11, 14, 20, tzinfo=UTC))
    tasks.coordinator = ScheduleService(session, tasks.clock)
    target = DAY + timedelta(days=1)
    created = await tasks.create(
        user.id, TaskCreate(title="Local day", type="routine", duration_min=15, planned_date=target)
    )
    assert created.status == TaskStatus.SCHEDULED
    assert (await placements(session, user.id))[created.id][0] >= at(
        target, 8, 0, "Asia/Yekaterinburg"
    )


@pytest.mark.parametrize("hour", [8, 10, 16])
async def test_deletion_keeps_past_started_and_completed_placements(
    session: AsyncSession, hour: int
) -> None:
    user, tasks = await scenario(session, "UTC")
    user_id = user.id
    start = at(DAY, hour, 0, "UTC")
    end = start + timedelta(minutes=30)
    async with session.begin():
        row = await make_task(
            session,
            user,
            type="routine",
            duration_min=30,
            planned_date=DAY,
            status=TaskStatus.DONE if hour == 16 else TaskStatus.SCHEDULED,
            completed_at=tasks.clock.now() if hour == 16 else None,
        )
        task_id = row.id
        plan = await make_schedule(session, user, date=DAY)
        await make_slot(session, plan, row, start_at=start, end_at=end)
    await tasks.delete(user_id, task_id, 1)
    assert (await placements(session, user_id))[task_id] == (start, end)


async def test_critical_transfer_respects_precise_deadline(session: AsyncSession) -> None:
    user, tasks = await scenario(session, "UTC")
    async with session.begin():
        profile = await session.get(UserProfile, user.id)
        assert profile is not None
        profile.birth_date = DAY - timedelta(days=14)
        profile.birth_at_utc = at(profile.birth_date, 12, 0, "UTC")
    due = at(DAY + timedelta(days=7), 18, 0, "UTC")
    created = await tasks.create(
        user.id,
        TaskCreate(
            title="Critical", type="intellectual", duration_min=60, planned_date=DAY, deadline=due
        ),
    )
    assert created.planned_date > DAY
    assert (await placements(session, user.id))[created.id][1] <= due
