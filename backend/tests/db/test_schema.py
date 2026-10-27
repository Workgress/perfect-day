from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleSlot, SlotKind
from app.modules.tasks.models import Task, TaskPriority, TaskStatus
from app.modules.users.models import Chronotype, User, UserProfile
from tests.db.factories import make_schedule, make_slot, make_task, make_user

pytestmark = pytest.mark.docker


async def _count(session: AsyncSession, model: type[object]) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def test_email_is_case_insensitive_unique(session: AsyncSession) -> None:
    await make_user(session, "Alexey@Example.ru")

    with pytest.raises(IntegrityError):
        await make_user(session, "alexey@example.ru")


async def test_profile_server_defaults(session: AsyncSession) -> None:
    user = await make_user(session)
    session.add(UserProfile(user_id=user.id))
    await session.flush()

    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    await session.refresh(profile)
    assert profile.timezone == "UTC"
    assert profile.work_days == [1, 2, 3, 4, 5]
    assert profile.lunch_duration_min == 60
    assert profile.birth_time_known is True


async def test_onboarding_requires_birth_data(session: AsyncSession) -> None:
    user = await make_user(session)
    session.add(UserProfile(user_id=user.id, onboarding_completed_at=datetime.now(UTC)))

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_completed_onboarding_with_birth_data(session: AsyncSession) -> None:
    user = await make_user(session)
    session.add(
        UserProfile(
            user_id=user.id,
            birth_date=date(1995, 3, 14),
            birth_at_utc=datetime(1995, 3, 14, 7, 0, tzinfo=UTC),
            chronotype=Chronotype.LARK,
            onboarding_completed_at=datetime.now(UTC),
        )
    )
    await session.flush()


@pytest.mark.parametrize("work_days", [[0, 1], [1, 8]])
async def test_work_days_must_be_weekdays(session: AsyncSession, work_days: list[int]) -> None:
    user = await make_user(session)
    session.add(UserProfile(user_id=user.id, work_days=work_days))

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_task_defaults(session: AsyncSession) -> None:
    user = await make_user(session)
    task = await make_task(session, user)
    await session.refresh(task)

    assert task.status is TaskStatus.PENDING
    assert task.priority is TaskPriority.MEDIUM
    assert task.version == 1
    assert task.is_pinned is False


@pytest.mark.parametrize("duration", [5, 480])
async def test_task_duration_bounds_accepted(session: AsyncSession, duration: int) -> None:
    user = await make_user(session)
    await make_task(session, user, duration_min=duration)


@pytest.mark.parametrize("duration", [4, 481])
async def test_task_duration_out_of_range(session: AsyncSession, duration: int) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_task(session, user, duration_min=duration)


async def test_task_title_not_blank(session: AsyncSession) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_task(session, user, title="   ")


async def test_pinned_task_requires_start(session: AsyncSession) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_task(session, user, is_pinned=True)


async def test_done_task_requires_completed_at(session: AsyncSession) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_task(session, user, status=TaskStatus.DONE)


async def test_only_one_active_schedule_per_day(session: AsyncSession) -> None:
    user = await make_user(session)
    await make_schedule(session, user, version=1)

    with pytest.raises(IntegrityError):
        await make_schedule(session, user, version=2)


async def test_inactive_versions_coexist_with_active(session: AsyncSession) -> None:
    user = await make_user(session)
    await make_schedule(session, user, version=1, is_active=False)
    await make_schedule(session, user, version=2, is_active=False)
    await make_schedule(session, user, version=3)

    assert await _count(session, Schedule) == 3


async def test_duplicate_schedule_version_rejected(session: AsyncSession) -> None:
    user = await make_user(session)
    await make_schedule(session, user, version=1, is_active=False)

    with pytest.raises(IntegrityError):
        await make_schedule(session, user, version=1, is_active=False)


@pytest.mark.parametrize("critical_level", [-1, 4])
async def test_critical_level_range(session: AsyncSession, critical_level: int) -> None:
    user = await make_user(session)

    with pytest.raises(IntegrityError):
        await make_schedule(session, user, critical_level=critical_level)


async def test_slot_end_after_start(session: AsyncSession) -> None:
    user = await make_user(session)
    schedule = await make_schedule(session, user)

    with pytest.raises(IntegrityError):
        await make_slot(
            session,
            schedule,
            end_at=datetime(2026, 10, 27, 9, 0, tzinfo=UTC),
        )


async def test_break_slot_cannot_reference_task(session: AsyncSession) -> None:
    user = await make_user(session)
    task = await make_task(session, user)
    schedule = await make_schedule(session, user)

    with pytest.raises(IntegrityError):
        await make_slot(session, schedule, task, kind=SlotKind.BREAK)


async def test_deleting_task_detaches_slot(session: AsyncSession) -> None:
    user = await make_user(session)
    task = await make_task(session, user)
    schedule = await make_schedule(session, user)
    slot = await make_slot(session, schedule, task)

    await session.execute(delete(Task).where(Task.id == task.id))
    await session.refresh(slot)

    assert slot.task_id is None


async def test_deleting_user_cascades(session: AsyncSession) -> None:
    user = await make_user(session)
    session.add(UserProfile(user_id=user.id))
    task = await make_task(session, user)
    schedule = await make_schedule(session, user)
    await make_slot(session, schedule, task)

    await session.execute(delete(User).where(User.id == user.id))
    session.expunge_all()

    for model in (UserProfile, Task, Schedule, ScheduleSlot):
        assert await _count(session, model) == 0
