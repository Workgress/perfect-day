from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.schedule.planning_schemas import PlacementCheckRequest
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.models import UserProfile
from tests.db.factories import make_schedule, make_slot, make_task
from tests.db.test_schedule_service import CLOCK, DAY, NOW, setup_user

pytestmark = pytest.mark.docker


def at(hour: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=UTC)


def request(task_id: UUID, hour: int = 14, version: int = 1) -> PlacementCheckRequest:
    return PlacementCheckRequest(
        task_id=task_id,
        version=version,
        planned_date=DAY,
        start_at=at(hour),
        end_at=at(hour) + timedelta(minutes=30),
    )


async def snapshot(session: AsyncSession, user_id: UUID) -> tuple:
    tasks = (
        await session.execute(
            select(
                Task.id,
                Task.version,
                Task.planned_date,
                Task.status,
                Task.updated_at,
            ).where(Task.user_id == user_id)
        )
    ).all()
    schedules = (
        await session.execute(
            select(
                Schedule.id,
                Schedule.version,
                Schedule.is_active,
                Schedule.summary,
            ).where(Schedule.user_id == user_id)
        )
    ).all()
    slots = (
        await session.execute(
            select(
                ScheduleSlot.id,
                ScheduleSlot.task_id,
                ScheduleSlot.start_at,
                ScheduleSlot.end_at,
            )
            .join(Schedule)
            .where(Schedule.user_id == user_id)
        )
    ).all()
    return tasks, schedules, slots


@pytest.mark.parametrize("hour", [10, 14, 15])
async def test_check_reads_real_occupancy_without_any_persistent_changes(
    session: AsyncSession,
    hour: int,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    selected = await make_task(
        session,
        user,
        planned_date=DAY,
        type="routine",
        duration_min=30,
        status=TaskStatus.SCHEDULED,
    )
    resident = await make_task(
        session,
        user,
        planned_date=DAY,
        type="routine",
        duration_min=30,
        status=TaskStatus.SCHEDULED,
    )
    selected_id, resident_id = selected.id, resident.id
    plan = await make_schedule(session, user, date=DAY)
    for item, start in ((selected, 14), (resident, 10)):
        await make_slot(
            session, plan, item, start_at=at(start), end_at=at(start) + timedelta(minutes=30)
        )
    before = await snapshot(session, user_id)
    await session.commit()
    async with session.begin():
        service = ScheduleService(session, CLOCK)
        result = await service.check_placement(user_id, request(selected_id, hour))
        assert result.allowed is (hour != 10)
        if hour == 10:
            refusal = next(
                reason for reason in result.reasons if reason.code == "INTERVAL_OCCUPIED"
            )
            assert refusal.conflicting_task_id == resident_id
            assert "10:00" in refusal.message and "10:30" in refusal.message
        else:
            assert result.reasons == ()
        assert await service.check_placement(user_id, request(selected_id, hour)) == result
    session.expire_all()
    assert await snapshot(session, user_id) == before


@pytest.mark.parametrize("case", ["foreign", "deleted", "missing", "stale"])
async def test_check_hides_unavailable_tasks_and_rejects_stale_version(
    session: AsyncSession,
    case: str,
) -> None:
    owner = await setup_user(session, completed=True)
    other = await setup_user(session, completed=True)
    row = await make_task(session, other if case == "foreign" else owner, planned_date=DAY)
    if case == "deleted":
        row.deleted_at = NOW
    owner_id, task_id = owner.id, row.id
    await session.commit()
    async with session.begin():
        with pytest.raises(AppError) as error:
            await ScheduleService(session, CLOCK).check_placement(
                owner_id,
                request(
                    uuid4() if case == "missing" else task_id, version=2 if case == "stale" else 1
                ),
            )
        assert error.value.body.code == (
            "TASK_VERSION_CONFLICT" if case == "stale" else "TASK_NOT_FOUND"
        )


@pytest.mark.parametrize("case", ["date_mismatch", "outside_day", "local_day"])
async def test_check_uses_profile_timezone_and_selected_local_date(
    session: AsyncSession,
    case: str,
) -> None:
    user = await setup_user(session, completed=True)
    row = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    user_id, task_id = user.id, row.id
    profile = await session.get(UserProfile, user_id)
    assert profile is not None
    profile.timezone = "Asia/Yekaterinburg"
    zone = timezone(timedelta(hours=5))
    start = datetime(DAY.year, DAY.month, DAY.day, 14, tzinfo=zone)
    body = PlacementCheckRequest(
        task_id=task_id,
        version=1,
        planned_date=DAY + timedelta(days=1) if case == "date_mismatch" else DAY,
        start_at=start + timedelta(days=1) if case == "outside_day" else start,
        end_at=start + timedelta(days=1, minutes=30)
        if case == "outside_day"
        else start + timedelta(minutes=30),
    )
    await session.commit()
    async with session.begin():
        result = await ScheduleService(session, CLOCK).check_placement(user_id, body)
    if case == "local_day":
        assert result.allowed and result.start_at == at(9)
    else:
        assert not result.allowed
        assert result.reasons[0].code == (
            "TASK_DATE_MISMATCH" if case == "date_mismatch" else "OUTSIDE_SELECTED_DATE"
        )


async def test_second_check_sees_new_occupancy_without_a_change_to_candidate_version(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    candidate = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    resident = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    plan = await make_schedule(session, user, date=DAY)
    occupied = await make_slot(
        session, plan, resident, start_at=at(15), end_at=at(15) + timedelta(minutes=30)
    )
    body, slot_id = request(candidate.id), occupied.id
    await session.commit()
    scheduler = ScheduleService(session, CLOCK)
    async with session.begin():
        assert (await scheduler.check_placement(user_id, body)).allowed
    async with session.begin():
        current = await session.get(ScheduleSlot, slot_id)
        assert current is not None
        current.start_at, current.end_at = body.start_at, body.end_at
    async with session.begin():
        result = await scheduler.check_placement(user_id, body)
        assert not result.allowed
        assert any(reason.code == "INTERVAL_OCCUPIED" for reason in result.reasons)


async def test_check_requires_completed_onboarding(session: AsyncSession) -> None:
    user = await setup_user(session)
    row = await make_task(session, user, planned_date=DAY)
    user_id, task_id = user.id, row.id
    await session.commit()
    async with session.begin():
        with pytest.raises(AppError) as error:
            await ScheduleService(session, CLOCK).check_placement(user_id, request(task_id))
        assert error.value.body.code == "ONBOARDING_REQUIRED"
