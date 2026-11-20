from copy import deepcopy
from dataclasses import replace
from datetime import time, timedelta

import pytest

from app.modules.planner.contracts import FutureDay, Interval, MoveRecommendation, PlanSlot, TaskRef
from app.modules.planner.engine import build_schedule
from tests.unit.test_planner_policy import DAY, at, context, future, task


def test_unplaced_recommendation_is_structured_and_does_not_apply_a_move() -> None:
    item = task(kind="routine")
    ctx = context(item, now=at(20), future_days=(future(),), allow_date_change=False)
    before = deepcopy(ctx)
    result = build_schedule(ctx)
    assert len(result.recommendations) == 1
    advice = result.recommendations[0]
    assert advice.task.task_id == item.ref.task_id
    assert advice.from_date == DAY and advice.to_date == DAY + timedelta(days=1)
    assert advice.reason_code == "NO_FEASIBLE_INTERVAL"
    assert "60 мин помещается целиком" in advice.explanation
    assert (
        DAY.isoformat() in advice.explanation and advice.to_date.isoformat() in advice.explanation
    )
    assert not result.moves and not result.future_plans and result.metrics.moved_min == 0
    assert not any(slot.task == item.ref for slot in result.slots)
    assert ctx == before and build_schedule(ctx) == result


def test_placed_low_priority_task_receives_overload_advice_without_losing_its_slot() -> None:
    item = task(kind="routine", duration=110, priority="low")
    ctx = context(item, future_days=(future(),), allow_date_change=False)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert result.recommendations[0].reason_code == "DAY_OVERLOADED"
    assert any(slot.task == item.ref for slot in result.slots)
    assert not result.moves and not result.future_plans and not result.unscheduled


def test_target_pin_and_full_day_are_respected_before_suggesting_another_day() -> None:
    incoming = task(kind="routine", duration=30)
    day = DAY + timedelta(days=1)
    resident = task(
        1,
        kind="routine",
        duration=60,
        planned_date=day,
        is_pinned=True,
        pinned_start=at(8, day=day),
    )
    fixed = PlanSlot(
        "task",
        Interval(at(8, day=day), at(9, day=day)),
        resident.ref,
        is_pinned=True,
        preservation="pinned",
    )
    occupied = FutureDay(day, (resident,), (fixed,))
    ctx = context(incoming, now=at(20), future_days=(occupied, future(2)), allow_date_change=False)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    original = deepcopy(ctx)
    result = build_schedule(ctx)
    assert result.recommendations[0].to_date == DAY + timedelta(days=2)
    assert ctx == original and ctx.future_days[0].fixed_slots == (fixed,)


@pytest.mark.parametrize("known", [False, True])
def test_unconfirmed_or_deadline_blocked_target_has_an_explanation_without_a_date(
    known: bool,
) -> None:
    item = task(kind="routine", deadline=at(18))
    ctx = context(
        item, now=at(20), future_days=(future(),) if known else (), allow_date_change=False
    )
    result = build_schedule(ctx)
    assert not result.recommendations
    warning = next(w for w in result.warnings if w.code == "MOVE_RECOMMENDATION_UNAVAILABLE")
    assert warning.task == item.ref and warning.target_date is None and warning.message
    assert not result.moves and not result.future_plans


def test_recommendations_share_tentative_capacity_without_collectively_overbooking() -> None:
    ctx = context(
        task(kind="routine"),
        task(1, kind="routine"),
        now=at(20),
        future_days=(future(),),
        allow_date_change=False,
    )
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert len(result.recommendations) == 1
    assert sum(w.code == "MOVE_RECOMMENDATION_UNAVAILABLE" for w in result.warnings) == 1
    assert not result.moves and not result.future_plans


def test_applied_transfer_is_not_also_returned_as_a_recommendation() -> None:
    item = task()
    result = build_schedule(
        context(item, elapsed=14, future_days=(future(),), allow_date_change=True)
    )
    assert result.moves and not result.recommendations


@pytest.mark.parametrize("field", ["task", "from_date", "to_date", "reason_code", "explanation"])
def test_internal_recommendations_reject_invalid_identity_dates_or_missing_reason(
    field: str,
) -> None:
    values = {
        "task": task().ref,
        "from_date": DAY,
        "to_date": DAY + timedelta(days=1),
        "reason_code": "DAY_OVERLOADED",
        "explanation": "Нагрузка дня превышена.",
    }
    invalid = {
        "task": TaskRef(task_index=0),
        "from_date": DAY + timedelta(days=1),
        "to_date": DAY + timedelta(days=8),
        "reason_code": " ",
        "explanation": " ",
    }
    values[field] = invalid[field]
    with pytest.raises(ValueError):
        MoveRecommendation(**values)
