from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import TaskStatus
from tests.db.factories import make_task
from tests.db.test_schedule_placement import snapshot
from tests.db.test_schedule_service import CLOCK, DAY, NOW, setup_user

pytestmark = pytest.mark.docker


async def prepared_advice(session: AsyncSession) -> tuple:
    user = await setup_user(session, completed=True)
    user_id = user.id
    target_day = DAY + timedelta(days=1)
    resident = await make_task(
        session, user, planned_date=target_day, type="routine", duration_min=30
    )
    service = ScheduleService(session, CLOCK)
    await service.replan(user_id, target_day, ScheduleTrigger.TASK_CREATED)
    target = (await service.repository.active(user_id, (target_day,)))[target_day]
    target_state = target.id, target.version, resident.id, resident.version
    incoming = await make_task(session, user, planned_date=DAY, type="routine", duration_min=60)
    incoming_id, incoming_version = incoming.id, incoming.version
    later = ScheduleService(session, FrozenClock(NOW + timedelta(hours=13)))
    result = await later.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    assert result.plan.recommendations and not result.plan.moves and not result.plan.future_plans
    source = (await later.repository.active(user_id, (DAY,)))[DAY]
    return user_id, incoming_id, incoming_version, source.id, result.plan, target_state


async def test_recommendations_round_trip_and_reads_do_not_change_tasks_or_either_day(
    session: AsyncSession,
) -> None:
    user_id, task_id, version, source_id, expected, target_state = await prepared_advice(session)
    before = await snapshot(session, user_id)
    await session.commit()
    session.expire_all()
    repository = ScheduleRepository(session)
    assert await repository.result(user_id, source_id) == expected
    reader = ScheduleReader(session)
    first = await reader.get_recommendations(user_id, DAY)
    assert first is not None and len(first) == 1
    assert first[0].task_id == task_id and first[0].from_date == DAY
    assert first[0].to_date == DAY + timedelta(days=1)
    assert first[0].reason_code == "NO_FEASIBLE_INTERVAL" and first[0].explanation
    assert await reader.get_recommendations(user_id, DAY) == first
    assert await snapshot(session, user_id) == before
    tasks, schedules, _ = before
    incoming = next(row for row in tasks if row.id == task_id)
    assert incoming.version == version and incoming.planned_date == DAY
    assert incoming.status == TaskStatus.PENDING
    target_id, target_version, resident_id, resident_version = target_state
    assert any(row.id == target_id and row.version == target_version for row in schedules)
    assert any(row.id == resident_id and row.version == resident_version for row in tasks)
    assert len(schedules) == 2


@pytest.mark.parametrize("version", [1, 2])
async def test_legacy_plans_without_recommendations_remain_readable(
    session: AsyncSession,
    version: int,
) -> None:
    user_id, _, _, source_id, expected, _ = await prepared_advice(session)
    repository = ScheduleRepository(session)
    source = (await repository.active(user_id, (DAY,)))[DAY]
    summary = {key: value for key, value in source.summary.items() if key != "recommendations"}
    source.summary = {**summary, "schema_version": version}
    await session.flush()
    assert await repository.result(user_id, source_id) == replace(expected, recommendations=())
    assert await ScheduleReader(session).get_recommendations(user_id, DAY) == ()


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "null",
        "uuid",
        "source_date",
        "target_date",
        "duplicate",
        "unrelated",
        "explanation",
        "reason_code",
    ],
)
async def test_incomplete_recommendations_are_rejected_instead_of_silently_disappearing(
    session: AsyncSession,
    corruption: str,
) -> None:
    user_id, _, _, source_id, _, _ = await prepared_advice(session)
    repository = ScheduleRepository(session)
    source = (await repository.active(user_id, (DAY,)))[DAY]
    summary = deepcopy(source.summary)
    if corruption == "missing":
        del summary["recommendations"]
    elif corruption == "null":
        summary["recommendations"] = None
    elif corruption == "duplicate":
        summary["recommendations"] *= 2
    else:
        field, value = {
            "uuid": ("task_id", "draft-0"),
            "source_date": ("from_date", (DAY - timedelta(days=1)).isoformat()),
            "target_date": ("to_date", DAY.isoformat()),
            "unrelated": ("task_id", str(uuid4())),
            "explanation": ("explanation", " "),
            "reason_code": ("reason_code", "не хватает места"),
        }[corruption]
        summary["recommendations"][0][field] = value
    source.summary = summary
    await session.flush()
    with pytest.raises(AppError) as error:
        await repository.result(user_id, source_id)
    assert error.value.body.code == "SCHEDULE_RESULT_INCOMPLETE"


async def test_recommendation_reader_is_owner_scoped(session: AsyncSession) -> None:
    user_id, _, _, _, _, _ = await prepared_advice(session)
    other = await setup_user(session, completed=True)
    reader = ScheduleReader(session)
    assert await reader.get_recommendations(user_id, DAY)
    assert await reader.get_recommendations(other.id, DAY) is None
