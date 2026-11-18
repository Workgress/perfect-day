from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.planner.contracts import (
    Interval,
    PlanMetrics,
    PlanResult,
    PlanSlot,
    PlanWarning,
    TaskRef,
    TaskStatusChange,
    UnscheduledTask,
)
from app.modules.schedule.adapters import quantized_plan
from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY, setup_user

pytestmark = pytest.mark.docker


def at(hour: int) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, tzinfo=UTC)


async def row_for(session: AsyncSession, user_id: UUID, day=DAY) -> Schedule:
    row = (await ScheduleRepository(session).active(user_id, (day,)))[day]
    return row


async def test_all_slot_kinds_and_unscheduled_reasons_round_trip_through_postgres(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    first = await make_task(session, user, planned_date=DAY)
    second = await make_task(session, user, planned_date=DAY)
    task = TaskRef(task_id=first.id)
    waiting = TaskRef(task_id=second.id)
    plan = PlanResult(
        DAY,
        "UTC",
        "planner-1.0.1",
        (
            PlanSlot(
                "task",
                Interval(at(9), at(10)),
                task,
                is_pinned=True,
                preservation="pinned",
                score=0.12345678,
                reason_codes=("CHRONOTYPE_PEAK",),
                explanation="Task placement",
            ),
            PlanSlot(
                "break",
                Interval(at(10), at(10) + timedelta(minutes=5)),
                preservation="system",
                reason_codes=("ACTIVITY_CHANGE",),
                explanation="Break",
            ),
            PlanSlot("lunch", Interval(at(12), at(13)), preservation="system", explanation="Lunch"),
            PlanSlot("rest", Interval(at(15), at(15) + timedelta(minutes=30)), explanation="Rest"),
        ),
        (UnscheduledTask(waiting, ("NO_FEASIBLE_INTERVAL", "DAY_CAPACITY_EXCEEDED")),),
        PlanMetrics(120, 60, 300, 60, 2, 0.585),
        status_changes=(TaskStatusChange(task, "pending", "scheduled"),),
        warnings=(PlanWarning("OVERLOADED", waiting, message="Capacity warning", level="warning"),),
    )
    expected = quantized_plan(plan)
    service = ScheduleService(session, CLOCK)
    saved = await service._save_plan(user.id, expected, ScheduleTrigger.TASK_UPDATED)
    user_id, schedule_id = user.id, saved.id
    await session.commit()
    session.expunge_all()
    async with session.begin():
        loaded = await ScheduleRepository(session).result(user_id, schedule_id)
        assert loaded == expected
        assert loaded is not None and loaded.slots[0].score == 0.1235
        assert {slot.kind for slot in loaded.slots} == {"task", "break", "lunch", "rest"}


@pytest.mark.parametrize("kind", ["empty", "overloaded", "critical"])
async def test_real_core_result_round_trips_including_empty_and_overloaded_days(
    session: AsyncSession, kind: str
) -> None:
    user = await setup_user(session, elapsed=644 if kind == "critical" else 2, completed=True)
    if kind != "empty":
        for _ in range(3 if kind == "overloaded" else 1):
            await make_task(session, user, planned_date=DAY, type="routine", duration_min=480)
    service = ScheduleService(session, CLOCK)
    result = await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    row = await row_for(session, user.id)
    user_id, schedule_id = user.id, row.id
    expected = result.plan
    await session.commit()
    session.expunge_all()
    async with session.begin():
        assert await ScheduleRepository(session).result(user_id, schedule_id) == expected
    if kind == "empty":
        assert not expected.unscheduled and not any(slot.task for slot in expected.slots)
    if kind == "overloaded":
        assert expected.unscheduled and all(item.reason_codes for item in expected.unscheduled)
    if kind == "critical":
        assert expected.metrics.critical_level == 3
        assert any(slot.kind == "rest" for slot in expected.slots)


async def test_source_result_keeps_exact_target_version_after_target_is_replanned(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    await make_task(session, user, planned_date=DAY, duration_min=60)
    service = ScheduleService(session, CLOCK)
    result = await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    assert result.plan.moves and result.plan.future_plans
    source = await row_for(session, user.id)
    source_id, user_id = source.id, user.id
    expected = result.plan
    target_day = result.plan.future_plans[0].day
    old_target = await row_for(session, user.id, target_day)
    old_id = old_target.id
    await service.replan(user.id, target_day, ScheduleTrigger.TASK_UPDATED)
    assert (await row_for(session, user.id, target_day)).id != old_id
    await session.commit()
    session.expunge_all()
    async with session.begin():
        loaded = await ScheduleRepository(session).result(user_id, source_id)
        assert loaded == expected
        assert loaded is not None and loaded.future_plans == expected.future_plans


async def test_new_version_replaces_slots_and_unscheduled_without_changing_old_result(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    first = await make_task(session, user, planned_date=DAY, type="routine", duration_min=480)
    second = await make_task(session, user, planned_date=DAY, type="routine", duration_min=480)
    service = ScheduleService(session, CLOCK)
    previous = await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    old = await row_for(session, user.id)
    old_id, user_id = old.id, user.id
    assert previous.plan.unscheduled
    first.deleted_at = CLOCK.now()
    second.duration_min = 15
    await session.flush()
    current = await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    new = await row_for(session, user.id)
    new_id = new.id
    assert new.version == old.version + 1
    assert not current.plan.unscheduled
    assert all(slot.task is None or slot.task.task_id != first.id for slot in current.plan.slots)
    await session.commit()
    session.expunge_all()
    async with session.begin():
        repository = ScheduleRepository(session)
        assert await repository.result(user_id, old_id) == previous.plan
        assert await repository.result(user_id, new_id) == current.plan


async def test_legacy_summary_without_new_metadata_is_readable(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    service = ScheduleService(session, CLOCK)
    calculated = await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    row = await row_for(session, user.id)
    row.summary = {
        key: value
        for key, value in row.summary.items()
        if key
        not in {
            "schema_version",
            "slot_count",
            "status_changes",
            "slot_preservations",
            "future_schedule_ids",
        }
    }
    await session.flush()
    loaded = await service.repository.result(user.id, row.id)
    assert loaded == replace(
        calculated.plan,
        status_changes=(),
        slots=tuple(replace(slot, preservation=None) for slot in calculated.plan.slots),
    )


async def test_results_are_owner_scoped_and_foreign_target_references_are_rejected(
    session: AsyncSession,
) -> None:
    first = await setup_user(session, completed=True)
    other = await setup_user(session, completed=True)
    service = ScheduleService(session, CLOCK)
    await service.replan(first.id, DAY, ScheduleTrigger.TASK_CREATED)
    await service.replan(other.id, DAY, ScheduleTrigger.TASK_CREATED)
    own = await row_for(session, first.id)
    foreign = await row_for(session, other.id)
    assert await service.repository.result(first.id, foreign.id) is None
    assert await service.repository.result(first.id, uuid4()) is None
    own.summary = {**own.summary, "future_schedule_ids": [str(foreign.id)]}
    await session.flush()
    with pytest.raises(AppError) as error:
        await service.repository.result(first.id, own.id)
    assert error.value.body.code == "SCHEDULE_RESULT_INCOMPLETE"


@pytest.mark.parametrize(
    "corruption", ["schema", "metrics", "identity", "target", "preservation", "missing_slot"]
)
async def test_incomplete_results_are_rejected_instead_of_returning_partial_data(
    session: AsyncSession, corruption: str
) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    service = ScheduleService(session, CLOCK)
    await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    row = await row_for(session, user.id)
    if corruption == "schema":
        row.summary = {**row.summary, "schema_version": 99}
    elif corruption == "metrics":
        row.summary = {**row.summary, "metrics": {}}
    elif corruption == "identity":
        slot = next(slot for slot in row.slots if slot.task_id is not None)
        slot.task_id = None
    elif corruption == "target":
        row.summary = {**row.summary, "future_schedule_ids": [str(uuid4())]}
    elif corruption == "missing_slot":
        await session.delete(row.slots[0])
    else:
        row.summary = {
            **row.summary,
            "slot_preservations": [
                {
                    "kind": "rest",
                    "task_id": None,
                    "start_at": at(0).isoformat(),
                    "end_at": at(1).isoformat(),
                    "preservation": "system",
                }
            ],
        }
    await session.flush()
    with pytest.raises(AppError) as error:
        await service.repository.result(user.id, row.id)
    assert error.value.body.code == "SCHEDULE_RESULT_INCOMPLETE"


async def test_started_slot_preservation_round_trips_without_recomputing_history(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, completed=True)
    await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
    original = await ScheduleService(session, CLOCK).replan(
        user.id, DAY, ScheduleTrigger.TASK_CREATED
    )
    placed = next(slot for slot in original.plan.slots if slot.task is not None)
    clock = FrozenClock(placed.interval.start + timedelta(minutes=1))
    service = ScheduleService(session, clock)
    current = await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    row = await row_for(session, user.id)
    user_id, schedule_id = user.id, row.id
    assert any(slot.preservation == "started" for slot in current.plan.slots)
    await session.commit()
    session.expunge_all()
    async with session.begin():
        assert await ScheduleRepository(session).result(user_id, schedule_id) == current.plan
