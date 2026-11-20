from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from tests.db.factories import make_task
from tests.db.test_schedule_placement import snapshot
from tests.db.test_schedule_service import CLOCK, DAY, NOW, setup_user

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("protection", ["pinned", "started"])
async def test_preserved_explanations_read_from_postgres_do_not_rewrite_original_metadata(
    session: AsyncSession,
    protection: str,
) -> None:
    user = await setup_user(session, completed=True)
    user_id = user.id
    pinned = protection == "pinned"
    row = await make_task(
        session,
        user,
        planned_date=DAY,
        duration_min=30,
        is_pinned=pinned,
        pinned_start=datetime(DAY.year, DAY.month, DAY.day, 14, tzinfo=UTC) if pinned else None,
    )
    task_id = row.id
    scheduler = ScheduleService(session, CLOCK)
    initial = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    original = next(slot for slot in initial.plan.slots if slot.task is not None)
    if not pinned:
        row.actual_start = NOW
    await session.flush()
    current = await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_UPDATED)
    retained = next(slot for slot in current.plan.slots if slot.task is not None)
    assert retained.interval == original.interval and retained.explanation == original.explanation
    assert retained.reason_codes == original.reason_codes and retained.score == original.score
    before = await snapshot(session, user_id)
    await session.commit()
    session.expire_all()
    reader = ScheduleReader(session)
    result = await reader.get_explanations(user_id, DAY)
    assert result is not None and not result.unscheduled_explanations
    exposed = result.placement_explanations[0]
    assert exposed.task_id == task_id and exposed.preservation == protection
    assert exposed.start_at == original.interval.start and exposed.end_at == original.interval.end
    assert exposed.reason_codes == (("PINNED_BY_USER" if pinned else "TASK_STARTED"),)
    assert "энергии" not in exposed.explanation
    assert await reader.get_explanations(user_id, DAY) == result
    assert await snapshot(session, user_id) == before


async def test_unplaced_explanation_round_trips_with_duration_and_actual_refusal_reasons(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    row = await make_task(session, user, planned_date=DAY, duration_min=180)
    user_id, task_id = user.id, row.id
    plan = (
        await ScheduleService(session, CLOCK).replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    ).plan
    saved = plan.unscheduled[0]
    assert saved.explanation and "180 мин" in saved.explanation
    await session.commit()
    session.expire_all()
    result = await ScheduleReader(session).get_explanations(user_id, DAY)
    assert result is not None
    exposed = result.unscheduled_explanations[0]
    assert exposed.task_id == task_id and exposed.planned_date == DAY
    assert exposed.reason_codes == saved.reason_codes and exposed.explanation == saved.explanation
    assert "лимит интенсивной работы" in exposed.explanation
    assert "Перенос даты запрещён" in exposed.explanation


async def test_legacy_unplaced_without_saved_text_uses_reasons_without_persisting_a_backfill(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    user_id = user.id
    await make_task(session, user, planned_date=DAY, duration_min=180)
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(user_id, DAY, ScheduleTrigger.TASK_CREATED)
    stored = (await scheduler.repository.active(user_id, (DAY,)))[DAY]
    summary = deepcopy(stored.summary)
    for item in summary["unscheduled"]:
        item.pop("explanation", None)
    stored.summary = summary
    await session.flush()
    before = await snapshot(session, user_id)
    result = await ScheduleReader(session).get_explanations(user_id, DAY)
    assert result is not None
    assert "лимит интенсивной работы" in result.unscheduled_explanations[0].explanation
    assert "180 мин" not in result.unscheduled_explanations[0].explanation
    assert await snapshot(session, user_id) == before
    assert stored.summary == summary


async def test_explanation_reader_is_owner_scoped_and_handles_missing_dates(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    other = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, duration_min=30)
    await ScheduleService(session, CLOCK).replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    reader = ScheduleReader(session)
    assert await reader.get_explanations(user.id, DAY) is not None
    assert await reader.get_explanations(other.id, DAY) is None
    row = (await ScheduleRepository(session).active(user.id, (DAY,)))[DAY]
    loaded = await ScheduleRepository(session).result(user.id, row.id)
    assert loaded is not None and loaded.slots
