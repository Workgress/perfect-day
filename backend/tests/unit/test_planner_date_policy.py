from dataclasses import replace
from datetime import timedelta

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
