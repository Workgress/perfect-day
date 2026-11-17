import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.planner.contracts import Interval, PlanSlot
from app.modules.schedule.dependencies import get_schedule_reader
from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.schedule.read_models import ScheduleReadResult
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import UserProfile
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user

pytestmark = pytest.mark.docker


async def test_reader_transfers_all_slot_kinds_and_unscheduled_reasons(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    for _ in range(3):
        await make_task(session, user, planned_date=DAY, type="routine", duration_min=480)
    scheduler = ScheduleService(session, CLOCK)
    result = await scheduler.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    assert result.plan.unscheduled
    extra = tuple(
        PlanSlot(
            kind,
            Interval(
                datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=UTC),
                datetime(DAY.year, DAY.month, DAY.day, hour, 5, tzinfo=UTC),
            ),
            explanation=kind,
        )
        for kind, hour in (("break", 19), ("rest", 20))
    )
    plan = replace(result.plan, slots=(*result.plan.slots, *extra))
    await scheduler._save_plan(user.id, plan, ScheduleTrigger.TASK_UPDATED)
    user_id = user.id
    await session.commit()
    document = await get_schedule_reader(session).get(user_id, DAY)
    assert document is not None
    assert {slot.kind for slot in document.slots} == {"task", "break", "lunch", "rest"}
    assert [(item.task_id, item.reason_codes) for item in document.unscheduled] == [
        (item.task.task_id, item.reason_codes) for item in plan.unscheduled
    ]
    assert document.metrics.planned_min == plan.metrics.planned_min
    assert document.metrics.load_factor == plan.metrics.load_factor
    assert all(slot.task_id is None for slot in document.slots if slot.kind != "task")
    assert document.slots == tuple(sorted(document.slots, key=lambda slot: slot.start_at))
    await session.commit()
    session.expunge_all()
    payload = json.loads(document.model_dump_json())
    assert isinstance(payload["slots"], list) and isinstance(payload["unscheduled"], list)
    assert all(slot["start_at"].endswith("Z") for slot in payload["slots"])
    assert ScheduleReadResult.model_validate(payload) == document
    assert set(payload) == {
        "id",
        "planned_date",
        "timezone",
        "version",
        "algorithm_version",
        "generated_at",
        "slots",
        "unscheduled",
        "metrics",
        "warnings",
        "moves",
    }
    assert all(
        set(slot)
        == {
            "id",
            "kind",
            "task_id",
            "start_at",
            "end_at",
            "is_pinned",
            "reason_codes",
            "explanation",
        }
        for slot in payload["slots"]
    )


async def test_reader_returns_latest_version_with_stable_slot_ids(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    scheduler = ScheduleService(session, CLOCK)
    await scheduler.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    reader = ScheduleReader(session)
    first = await reader.get(user.id, DAY)
    assert first is not None and first.version == 1
    assert await reader.get(user.id, DAY) == first
    await scheduler.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    current = await reader.get(user.id, DAY)
    assert current is not None and current.version == 2 and current.id != first.id
    assert {slot.id for slot in current.slots}.isdisjoint(slot.id for slot in first.slots)
    assert first.version == 1


async def test_reader_returns_none_without_building_missing_schedule(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY)
    assert await ScheduleReader(session).get(user.id, DAY) is None
    assert await session.scalar(select(Schedule).where(Schedule.user_id == user.id)) is None


async def test_reader_isolates_users_and_keeps_an_empty_day_distinct_from_missing(
    session: AsyncSession,
) -> None:
    owner = await setup_user(session, completed=True)
    other = await setup_user(session, completed=True)
    await ScheduleService(session, CLOCK).replan(owner.id, DAY, ScheduleTrigger.TASK_CREATED)
    reader = ScheduleReader(session)
    empty = await reader.get(owner.id, DAY)
    assert (
        empty is not None
        and not empty.unscheduled
        and not any(slot.task_id for slot in empty.slots)
    )
    assert await reader.get(other.id, DAY) is None
    assert await reader.get(owner.id, DAY + timedelta(days=1)) is None


async def test_reader_keeps_saved_timezone_after_profile_change(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await ScheduleService(session, CLOCK).replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    reader = ScheduleReader(session)
    original = await reader.get(user.id, DAY)
    assert original is not None
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.timezone = "America/New_York"
    await session.flush()
    assert await reader.get(user.id, DAY) == original


async def test_reading_does_not_write_or_recalculate(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await ScheduleService(session, CLOCK).replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    user_id = user.id
    await session.commit()
    connection = await session.connection()
    statements = []

    def record(*args: Any) -> None:
        statements.append(args[2].lstrip().split()[0].upper())

    event.listen(connection.sync_connection, "before_cursor_execute", record)
    try:
        reader = ScheduleReader(session)
        assert await reader.get(user_id, DAY) == await reader.get(user_id, DAY)
        assert statements and set(statements) == {"SELECT"}
        assert not session.new and not session.dirty and not session.deleted
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record)


async def test_reader_passes_moves_and_warnings_without_internal_future_graph(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    await make_task(session, user, planned_date=DAY, duration_min=60)
    result = await ScheduleService(session, CLOCK).replan(
        user.id, DAY, ScheduleTrigger.TASK_CREATED
    )
    assert result.plan.moves
    source = await ScheduleReader(session).get(user.id, DAY)
    assert source is not None
    move = source.moves[0]
    assert (move.task_id, move.from_date, move.to_date, move.reason_code) == (
        result.plan.moves[0].task.task_id,
        DAY,
        result.plan.moves[0].to_date,
        result.plan.moves[0].reason_code,
    )
    assert source.warnings and all(item.code for item in source.warnings)
    target = await ScheduleReader(session).get(user.id, move.to_date)
    assert target is not None and any(slot.task_id == move.task_id for slot in target.slots)
    assert "future_plans" not in source.model_dump() and "status_changes" not in source.model_dump()


async def test_reader_propagates_incomplete_result_instead_of_hiding_tasks(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    service = ScheduleService(session, CLOCK)
    await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    row = (await service.repository.active(user.id, (DAY,)))[DAY]
    row.summary = {**row.summary, "slot_count": -1}
    await session.flush()
    with pytest.raises(AppError) as error:
        await ScheduleReader(session).get(user.id, DAY)
    assert error.value.body.code == "SCHEDULE_RESULT_INCOMPLETE"
