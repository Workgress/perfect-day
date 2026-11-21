from dataclasses import replace
from datetime import time, timedelta

import pytest

from app.modules.planner import engine
from app.modules.planner.contracts import FutureDay, Interval, PlanSlot
from app.modules.planner.engine import _CalculationCache, build_schedule
from app.modules.planner.replan import replan_remaining_day
from scripts.benchmark_planner import workloads
from scripts.generate_planner_cases import Case, cases
from tests.unit.test_planner_policy import DAY, at, context, future, task

HORIZON_CASES = [case for case in cases() if case.context.future_days]
HORIZON_CASES.append(
    Case("overloaded-100", ("overload",), workloads()["overloaded_100_occupied_horizon"])
)


@pytest.mark.parametrize("case", HORIZON_CASES, ids=lambda case: case.id)
def test_budget_pruning_matches_the_full_target_search(
    case, monkeypatch: pytest.MonkeyPatch
) -> None:
    def calculate():
        return (
            replan_remaining_day(case.context, case.previous).plan
            if case.previous is not None
            else build_schedule(case.context)
        )

    optimized = calculate()
    monkeypatch.setattr(_CalculationCache, "fits_target_budget", lambda *args: True)

    class NoReuse(set):
        def add(self, value):
            pass

    original_init = _CalculationCache.__init__

    def without_probe_cache(self):
        original_init(self)
        self.failed_targets = NoReuse()

    monkeypatch.setattr(_CalculationCache, "__init__", without_probe_cache)
    full_build = engine._build_day

    def without_early_exit(*args, **kwargs):
        kwargs["stop_on_unplaced"] = False
        return full_build(*args, **kwargs)

    monkeypatch.setattr(engine, "_build_day", without_early_exit)
    assert calculate() == optimized


def test_inserting_routine_work_may_replace_a_derived_break_without_losing_capacity() -> None:
    day = DAY + timedelta(days=1)
    first = task(1, duration=30, planned_date=day, is_pinned=True, pinned_start=at(8, day=day))
    second = task(2, duration=30, planned_date=day, is_pinned=True, pinned_start=at(9, day=day))
    fixed = tuple(
        PlanSlot(
            "task",
            Interval(item.pinned_start, item.pinned_start + timedelta(minutes=30)),
            item.ref,
            is_pinned=True,
            preservation="pinned",
        )
        for item in (first, second)
    )
    incoming = task(kind="routine", duration=30)
    ctx = context(
        incoming,
        now=at(20),
        future_days=(FutureDay(day, (first, second), fixed),),
        allow_date_change=False,
    )
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9, 30), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert len(result.recommendations) == 1 and result.recommendations[0].to_date == day


def test_skipped_resident_does_not_consume_the_target_budget() -> None:
    incoming = task(kind="routine", duration=60)
    skipped = task(1, kind="routine", duration=480, status="skipped")
    ctx = context(incoming, now=at(20), future_days=(future(1, skipped),), allow_date_change=False)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert len(result.recommendations) == 1


def test_failed_probe_is_not_reused_for_a_different_deadline() -> None:
    day = DAY + timedelta(days=1)
    blocked = task(kind="routine", duration=30, deadline=at(8, 30, day=day))
    fitting = task(1, kind="routine", duration=30, deadline=at(9, day=day))
    resident = task(
        2,
        kind="routine",
        duration=30,
        planned_date=day,
        is_pinned=True,
        pinned_start=at(8, day=day),
    )
    fixed = PlanSlot(
        "task",
        Interval(at(8, day=day), at(8, 30, day=day)),
        resident.ref,
        is_pinned=True,
        preservation="pinned",
    )
    ctx = context(
        blocked,
        fitting,
        now=at(20),
        future_days=(FutureDay(day, (resident,), (fixed,)),),
        allow_date_change=False,
    )
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    assert [item.task for item in build_schedule(ctx).recommendations] == [fitting.ref]


@pytest.mark.parametrize("ordering", ["identity", "created_at"])
def test_failed_probe_is_not_reused_when_tie_order_changes(ordering: str) -> None:
    day = DAY + timedelta(days=1)
    early = task(0, kind="routine", duration=30, preferred_start=time(8), deadline=at(9, day=day))
    late = replace(early, ref=task(9).ref)
    resident = task(
        4,
        kind="routine",
        duration=30,
        preferred_start=time(8),
        deadline=at(8, 30, day=day),
        planned_date=day,
    )
    if ordering == "created_at":
        early = replace(early, created_at=at(1))
        resident = replace(resident, created_at=at(2))
        late = replace(late, created_at=at(3))
    ctx = context(
        early, late, now=at(20), future_days=(FutureDay(day, (resident,)),), allow_date_change=False
    )
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    assert [item.task for item in build_schedule(ctx).recommendations] == [late.ref]
