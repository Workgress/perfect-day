from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskPatch
from app.modules.tasks.service import TaskService
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, NOW, setup_user

pytestmark = pytest.mark.docker


def at(hour: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=UTC)


async def test_early_start_and_pin_survive_replan_and_database_reload(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    pinned = await make_task(
        session, user, planned_date=DAY, type="routine", is_pinned=True, pinned_start=at(10)
    )
    started = await make_task(
        session, user, planned_date=DAY, type="routine", is_pinned=True, pinned_start=at(14)
    )
    scheduler = ScheduleService(session, CLOCK)
    original = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    saved = {slot.task.task_id: slot for slot in original.plan.slots if slot.task is not None}
    pinned_id, started_id = pinned.id, started.id
    started.is_pinned = False
    started.pinned_start = None
    started.actual_start = NOW
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    await session.flush()
    await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_UPDATED)
    await session.commit()
    session.expire_all()
    repository = ScheduleRepository(session)
    active = (await repository.active(user_id, (DAY,)))[DAY]
    restored = await repository.result(user_id, active.id)
    assert restored is not None
    slots = {slot.task.task_id: slot for slot in restored.slots if slot.task is not None}
    for task_id, preservation in ((pinned_id, "pinned"), (started_id, "started")):
        assert slots[task_id].interval == saved[task_id].interval
        assert slots[task_id].score == saved[task_id].score
        assert slots[task_id].explanation == saved[task_id].explanation
        assert slots[task_id].reason_codes == saved[task_id].reason_codes
        assert slots[task_id].preservation == preservation
    read = await ScheduleReader(session).get(user_id, DAY)
    assert read is not None
    for item in read.slots:
        if item.task_id in (pinned_id, started_id):
            assert item.start_at == saved[item.task_id].interval.start
            assert item.end_at == saved[item.task_id].interval.end
    again = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert not any(change.task.task_id in (pinned_id, started_id) for change in again.changes)


@pytest.mark.parametrize("change", ["duration", "date"])
async def test_invalid_edit_of_early_started_task_rolls_back_task_and_schedule(
    session: AsyncSession, change: str
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    task = await make_task(
        session, user, planned_date=DAY, type="routine", is_pinned=True, pinned_start=at(14)
    )
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    task.is_pinned = False
    task.pinned_start = None
    task.actual_start = NOW
    await session.commit()
    task_id, version = task.id, task.version
    original_id = (await ScheduleRepository(session).active(user_id, (DAY,)))[DAY].id
    await session.commit()
    body = TaskPatch.model_validate(
        {
            "version": version,
            **(
                {"duration_min": 30}
                if change == "duration"
                else {"planned_date": (DAY + timedelta(days=1)).isoformat()}
            ),
        }
    )
    with pytest.raises(AppError) as error:
        await TaskService(session, CLOCK, coordinator=scheduler).patch(user_id, task_id, body)
    assert error.value.status_code == 409
    if change == "duration":
        assert error.value.body.details["reason_code"] == "FIXED_TASK_MISMATCH"
        assert error.value.body.details["task_id"] == str(task_id)
    current = await session.get(Task, task_id)
    assert current is not None
    assert current.version == version and current.duration_min == 60 and current.planned_date == DAY
    rows = list(await session.scalars(select(Schedule).where(Schedule.user_id == user_id)))
    assert len(rows) == 1 and rows[0].id == original_id and rows[0].is_active
