from dataclasses import replace
from datetime import time, timedelta

import pytest

from app.modules.planner.contracts import FutureDay, PlanContext
from app.modules.planner.replan import replan_remaining_day
from tests.unit.test_planner_replan import DAY, at, context, slot, task


@pytest.mark.parametrize("permission", [False, True])
def test_critical_transfer_requires_permission_even_with_confirmed_free_day(
    permission: bool,
) -> None:
    item = task(duration=180, kind="intellectual", status="scheduled")
    ctx = context(
        item,
        elapsed=14,
        now=at(7),
        future_days=(FutureDay(DAY + timedelta(days=1)),),
        allow_date_change=permission,
    )
    previous = slot(replace(item, duration_min=60), 14)
    result = replan_remaining_day(ctx, (previous,)).plan
    if permission:
        assert len(result.moves) == len(result.future_plans) == 1
        assert result.moves[0].task == item.ref
        assert not result.unscheduled
    else:
        assert not result.moves and not result.future_plans and result.metrics.moved_min == 0
        assert not any(saved.task == item.ref for saved in result.slots)
        assert result.unscheduled[0].task == item.ref
        assert "INTENSITY_CAPACITY_EXCEEDED" in result.unscheduled[0].reason_codes
        assert "DATE_CHANGE_FORBIDDEN" in result.unscheduled[0].reason_codes
        assert any(change.next == "pending" for change in result.status_changes)
        warning = next(w for w in result.warnings if w.code == "DATE_CHANGE_FORBIDDEN")
        assert warning.task == item.ref and DAY.isoformat() in warning.message
        assert warning.target_date is None
    assert item.planned_date == DAY and ctx.tasks == (item,)


def test_default_policy_keeps_fitting_critical_work_on_original_date() -> None:
    item = task(duration=60, kind="intellectual")
    base = context(item, elapsed=14, now=at(7))
    ctx = PlanContext(
        base.profile,
        DAY,
        base.now,
        (item,),
        "replan",
        future_days=(FutureDay(DAY + timedelta(days=1)),),
    )
    assert ctx.allow_date_change is False
    result = replan_remaining_day(ctx).plan
    assert any(saved.task == item.ref for saved in result.slots)
    assert not result.moves and not result.future_plans and not result.unscheduled
    assert not any(w.code == "DATE_CHANGE_FORBIDDEN" for w in result.warnings)


def test_unplaced_task_can_receive_advice_without_changing_date() -> None:
    item = task(duration=60)
    ctx = context(item, now=at(20), future_days=(FutureDay(DAY + timedelta(days=1)),))
    result = replan_remaining_day(ctx).plan
    assert "NO_AVAILABLE_TIME" in result.unscheduled[0].reason_codes
    assert "DATE_CHANGE_FORBIDDEN" in result.unscheduled[0].reason_codes
    assert any(w.code == "SUGGESTED_MOVE" and w.task == item.ref for w in result.warnings)
    assert not result.moves and not result.future_plans


@pytest.mark.parametrize("permission", [None, 0, 1, "false", "true"])
def test_internal_policy_also_requires_a_boolean(permission: object) -> None:
    with pytest.raises(ValueError, match="allow_date_change must be a boolean"):
        replace(context(), allow_date_change=permission)


@pytest.mark.parametrize("permission", [False, True])
def test_date_lock_keeps_unplaced_critical_task_without_transfer_or_advice(
    permission: bool,
) -> None:
    item = task(duration=180, kind="intellectual", is_date_locked=True)
    ctx = context(
        item,
        elapsed=14,
        now=at(7),
        future_days=(FutureDay(DAY + timedelta(days=1)),),
        allow_date_change=permission,
    )
    result = replan_remaining_day(ctx).plan
    assert not result.moves and not result.future_plans and not result.recommendations
    assert result.metrics.moved_min == 0
    assert result.unscheduled[0].task == item.ref
    assert "INTENSITY_CAPACITY_EXCEEDED" in result.unscheduled[0].reason_codes
    assert "DATE_CHANGE_FORBIDDEN" in result.unscheduled[0].reason_codes
    assert "оставлена на выбранной дате без времени" in result.unscheduled[0].explanation
    assert not any(
        warning.code
        in {"SUGGESTED_MOVE", "MOVE_RECOMMENDATION_UNAVAILABLE", "CRITICAL_MOVE_UNAVAILABLE"}
        for warning in result.warnings
    )
    assert ctx.tasks == (item,) and item.planned_date == DAY


def test_date_lock_allows_time_to_be_chosen_again_within_the_day() -> None:
    item = task(is_date_locked=True, preferred_start=time(9))
    result = replan_remaining_day(context(item, now=at(11)), (slot(item, 14),)).plan
    placed = next(saved for saved in result.slots if saved.task == item.ref)
    assert placed.interval.start >= at(11)
    assert placed.interval.start.date() == placed.interval.end.date() == DAY
    assert placed.interval.start != at(14)
    assert not placed.is_pinned and not result.unscheduled
    assert not result.moves and not result.recommendations


@pytest.mark.parametrize("overload", [False, True])
def test_date_lock_suppresses_advice_for_unplaced_and_overloaded_tasks(overload: bool) -> None:
    item = task(duration=110 if overload else 30, priority="low", is_date_locked=True)
    ctx = context(
        item,
        now=at(7) if overload else at(20),
        future_days=(FutureDay(DAY + timedelta(days=1)),),
    )
    if overload:
        ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = replan_remaining_day(ctx).plan
    assert bool(result.unscheduled) is not overload
    assert not result.recommendations and not result.moves
    assert not any(warning.code == "SUGGESTED_MOVE" for warning in result.warnings)


def test_date_lock_is_per_task_and_can_be_disabled() -> None:
    locked = task(duration=60, kind="intellectual", is_date_locked=True)
    unlocked = task(1, duration=60, kind="intellectual")
    ctx = context(
        locked,
        unlocked,
        elapsed=14,
        now=at(7),
        future_days=(FutureDay(DAY + timedelta(days=1)),),
        allow_date_change=True,
    )
    result = replan_remaining_day(ctx).plan
    assert {move.task for move in result.moves} == {unlocked.ref}
    assert any(saved.task == locked.ref for saved in result.slots)
    released = replace(ctx, tasks=(replace(locked, is_date_locked=False), unlocked))
    assert {move.task for move in replan_remaining_day(released).plan.moves} == {
        locked.ref,
        unlocked.ref,
    }


@pytest.mark.parametrize("value", [None, 0, 1, "false", "true"])
def test_date_lock_requires_a_boolean(value: object) -> None:
    with pytest.raises(ValueError, match="is_date_locked must be a boolean"):
        replace(task(), is_date_locked=value)
