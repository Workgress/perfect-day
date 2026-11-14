from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.planner.constraints import ConstraintError
from app.modules.planner.contracts import (
    FutureDay,
    Interval,
    PlacementChange,
    PlanContext,
    PlanProfile,
    PlanSlot,
    PlanTask,
    TaskKind,
    TaskRef,
)
from app.modules.planner.replan import replan_remaining_day

DAY = date(2026, 11, 14)


def at(hour: int, minute: int = 0, *, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def task(index: int = 0, duration: int = 30, kind: TaskKind = "routine", **kw: Any) -> PlanTask:
    return replace(PlanTask(TaskRef(task_id=UUID(int=index + 1)), kind, duration, DAY), **kw)


def slot(item: PlanTask, hour: int, minute: int = 0, **kw: Any) -> PlanSlot:
    start = at(hour, minute)
    return replace(
        PlanSlot(
            "task",
            Interval(start, start + timedelta(minutes=item.duration_min)),
            item.ref,
            is_pinned=item.is_pinned,
            score=0.7,
            reason_codes=("SAVED",),
            explanation="Прежнее объяснение",
        ),
        **kw,
    )


def system(kind: Any, hour: int, minute: int = 0, duration: int = 30) -> PlanSlot:
    start = at(hour, minute)
    return PlanSlot(
        kind, Interval(start, start + timedelta(minutes=duration)), explanation="Системная история"
    )


def context(*tasks: PlanTask, elapsed: int = 2, **kw: Any) -> PlanContext:
    profile = PlanProfile(
        at(12) - timedelta(days=elapsed),
        "UTC",
        "dove",
        time(8),
        time(18),
        time(23),
        work_days=(1, 2, 3, 4, 5, 6, 7),
    )
    mode = kw.pop("mode", "replan")
    return replace(PlanContext(profile, DAY, at(10), tasks, mode), **kw)


def find_task(slots: tuple[PlanSlot, ...], ref: TaskRef) -> PlanSlot:
    return next(item for item in slots if item.task == ref)


def test_empty_replan_builds_future_system_slots_without_inventing_task_changes() -> None:
    result = replan_remaining_day(context())
    assert not result.changes
    assert [item.kind for item in result.plan.slots] == ["lunch"]
    assert result.plan.slots[0].explanation
    assert result.plan.metrics.capacity_min == 540


def test_past_started_done_and_pinned_slots_keep_their_intervals_and_saved_metadata() -> None:
    past = task(0, 60)
    started = task(1, 60)
    done = task(2, status="done")
    pinned = task(3, is_pinned=True, pinned_start=at(14))
    added = task(4, 15)
    previous = (slot(past, 8), slot(started, 9, 30), slot(pinned, 14), slot(done, 15))
    ctx = context(past, started, done, pinned, added)
    result = replan_remaining_day(ctx, previous)
    assert [change.task for change in result.changes] == [added.ref]
    assert result.changes[0].kind == "added"
    for saved, reason in zip(previous, ("past", "started", "pinned", "done"), strict=True):
        actual = find_task(result.plan.slots, saved.task)  # type: ignore[arg-type]
        assert actual.preservation == reason
        assert replace(actual, preservation=saved.preservation) == saved
    assert find_task(result.plan.slots, added.ref).interval.start >= ctx.now
    assert ctx.fixed_slots == () and all(item.preservation is None for item in previous)


@pytest.mark.parametrize(
    ("delta", "preservation"),
    [
        (timedelta(microseconds=-1), None),
        (timedelta(), "started"),
        (timedelta(microseconds=1), "started"),
        (timedelta(hours=1), "past"),
    ],
)
def test_half_open_history_boundaries_use_exact_instants(
    delta: timedelta, preservation: str | None
) -> None:
    item = task(duration=60)
    ctx = context(item, now=at(9) + delta)
    result = replan_remaining_day(ctx, (slot(item, 9),))
    actual = find_task(result.plan.slots, item.ref)
    assert actual.preservation == preservation
    if preservation:
        assert actual.interval == Interval(at(9), at(10))
    else:
        assert actual.interval.start >= ctx.now


def test_new_work_never_starts_before_now_or_overlaps_a_begun_task() -> None:
    started, added = task(duration=60), task(1, 15, preferred_start=time(10))
    ctx = context(started, added, now=at(10) + timedelta(microseconds=1))
    result = replan_remaining_day(ctx, (slot(started, 9, 30),))
    fresh = find_task(result.plan.slots, added.ref)
    assert fresh.interval.start >= at(10, 30)
    assert all(
        left.interval.end <= right.interval.start for left, right in pairwise(result.plan.slots)
    )


def test_deleting_a_future_task_releases_its_interval_and_reports_removal() -> None:
    deleted = task()
    old = slot(deleted, 14)
    result = replan_remaining_day(context(), (old,))
    assert not any(item.task for item in result.plan.slots)
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.task == deleted.ref and change.kind == "removed"
    assert (
        change.before == old and change.after is None and change.reason_codes == ("TASK_REMOVED",)
    )


@pytest.mark.parametrize("hour", [8, 9])
def test_missing_historical_task_snapshot_is_an_error_instead_of_silent_history_loss(
    hour: int,
) -> None:
    old = slot(task(duration=120), hour)
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(), (old,))
    assert caught.value.code == "HISTORY_TASK_REQUIRED"


def test_skipping_a_future_pin_removes_it_without_creating_an_active_status_change() -> None:
    item = task(status="skipped", is_pinned=True, pinned_start=at(14))
    result = replan_remaining_day(context(item), (slot(item, 14),))
    assert not result.plan.unscheduled and not result.plan.status_changes
    assert result.plan.metrics.requested_min == result.plan.metrics.planned_min == 0
    assert result.changes[0].reason_codes == ("TASK_SKIPPED",)


@pytest.mark.parametrize("now", [time(8, 30), time(9, 5)])
def test_skipped_history_is_retained_without_counting_it_as_new_work_or_fatigue(now: time) -> None:
    skipped = task(duration=60, kind="intellectual", status="skipped")
    next_task = task(1, 5, "physical", is_pinned=True, pinned_start=at(9, 10))
    ctx = context(skipped, next_task, now=datetime.combine(DAY, now, UTC))
    old = slot(skipped, 8)
    result = replan_remaining_day(ctx, (old,))
    assert find_task(result.plan.slots, skipped.ref).interval == old.interval
    assert result.plan.metrics.requested_min == result.plan.metrics.planned_min == 5
    assert not any(item.kind == "break" for item in result.plan.slots)
    assert not any(change.task == skipped.ref for change in result.plan.status_changes)
    assert not any(change.task == skipped.ref for change in result.changes)


def test_editing_a_future_task_uses_current_duration_and_preferences() -> None:
    old_task = task()
    current = replace(old_task, duration_min=45, preferred_start=time(14))
    result = replan_remaining_day(context(current), (slot(old_task, 13),))
    fresh = find_task(result.plan.slots, current.ref)
    assert fresh.interval.end - fresh.interval.start == timedelta(minutes=45)
    assert at(13, 30) <= fresh.interval.start <= at(14, 30)
    assert result.changes[0].kind == "moved"


@pytest.mark.parametrize("status", ["pending", "done"])
def test_duration_edits_cannot_rewrite_a_protected_interval(status: str) -> None:
    item = task(status=status)
    old = slot(item, 9, 30)
    changed = replace(item, duration_min=45)
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(changed), (old,))
    assert caught.value.code == "FIXED_TASK_MISMATCH"
    assert old.interval.end == at(10) and changed.duration_min == 45


def test_manual_pin_moves_future_work_to_the_exact_requested_minute() -> None:
    old_task = task()
    current = replace(old_task, is_pinned=True, pinned_start=at(14, 7))
    result = replan_remaining_day(context(current), (slot(old_task, 13, 15),))
    fresh = find_task(result.plan.slots, current.ref)
    assert fresh.interval == Interval(at(14, 7), at(14, 37))
    assert fresh.is_pinned and "PINNED_BY_USER" in fresh.reason_codes
    assert result.changes[0].kind == "moved"


def test_unchanged_future_pin_retains_saved_metadata() -> None:
    item = task(is_pinned=True, pinned_start=at(14, 7))
    old = slot(item, 14, 7)
    result = replan_remaining_day(context(item), (old,))
    assert replace(find_task(result.plan.slots, item.ref), preservation=None) == old
    assert not result.changes


def test_future_pin_duration_can_change_without_using_the_old_end() -> None:
    item = task(is_pinned=True, pinned_start=at(14, 7))
    current = replace(item, duration_min=45)
    result = replan_remaining_day(context(current), (slot(item, 14, 7),))
    assert find_task(result.plan.slots, item.ref).interval == Interval(at(14, 7), at(14, 52))
    assert result.changes[0].kind == "moved"


def test_unpinning_future_work_makes_it_eligible_for_ranking_again() -> None:
    item = task(is_pinned=True, pinned_start=at(14), preferred_start=time(14))
    current = replace(item, is_pinned=False)
    result = replan_remaining_day(context(current), (slot(item, 14),))
    fresh = find_task(result.plan.slots, item.ref)
    assert not fresh.is_pinned and fresh.preservation is None
    assert at(13, 30) <= fresh.interval.start <= at(14, 30)


def test_unpinning_a_started_task_keeps_its_interval_and_updates_only_the_pin_flag() -> None:
    item = task(duration=60, is_pinned=True, pinned_start=at(9, 30))
    old = slot(item, 9, 30)
    current = replace(item, is_pinned=False)
    result = replan_remaining_day(context(current), (old,))
    fresh = find_task(result.plan.slots, item.ref)
    assert fresh.interval == old.interval and not fresh.is_pinned
    assert fresh.explanation == old.explanation and fresh.preservation == "started"
    assert result.changes[0].kind == "updated"


def test_manual_pin_cannot_move_a_started_task() -> None:
    item = task(duration=60)
    current = replace(item, is_pinned=True, pinned_start=at(14))
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(current), (slot(item, 9, 30),))
    assert caught.value.code == "FIXED_TASK_MISMATCH"


def test_marking_future_work_done_preserves_it_even_outside_the_new_work_window() -> None:
    done = task(status="done")
    ctx = context(done)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(11)))
    result = replan_remaining_day(ctx, (slot(done, 15),))
    assert find_task(result.plan.slots, done.ref).interval == Interval(at(15), at(15, 30))
    assert not result.changes and not result.plan.status_changes


def test_completed_work_requires_a_saved_slot_instead_of_inventing_completion_time() -> None:
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(task(status="done")))
    assert caught.value.code == "FIXED_SLOT_REQUIRED"


def test_undoing_future_completion_releases_the_old_done_reservation() -> None:
    item = task(preferred_start=time(14))
    old = slot(item, 13, preservation="done")
    result = replan_remaining_day(context(item), (old,))
    fresh = find_task(result.plan.slots, item.ref)
    assert fresh.preservation is None and at(13, 30) <= fresh.interval.start <= at(14, 30)


def test_new_work_window_retains_history_outside_it_and_restricts_new_work() -> None:
    old_task, added = task(duration=60), task(1, 15)
    ctx = context(old_task, added)
    ctx = replace(
        ctx, profile=replace(ctx.profile, work_start=time(14), work_end=time(16), chronotype="owl")
    )
    result = replan_remaining_day(ctx, (slot(old_task, 8),))
    assert find_task(result.plan.slots, old_task.ref).interval == Interval(at(8), at(9))
    fresh = find_task(result.plan.slots, added.ref)
    assert at(14) <= fresh.interval.start < fresh.interval.end <= at(16)


@pytest.mark.parametrize("now", [time(12), time(12, 30), time(14)])
def test_begun_or_taken_lunch_is_not_recreated_after_a_profile_change(now: time) -> None:
    lunch = system("lunch", 12, duration=60)
    ctx = context(now=datetime.combine(DAY, now, UTC))
    ctx = replace(ctx, profile=replace(ctx.profile, lunch_start=time(15)))
    result = replan_remaining_day(ctx, (lunch,))
    lunches = [item for item in result.plan.slots if item.kind == "lunch"]
    assert lunches == [replace(lunch, preservation="system")]
    assert result.plan.metrics.capacity_min == 540


def test_future_lunch_is_rebuilt_using_the_new_profile() -> None:
    ctx = context()
    ctx = replace(ctx, profile=replace(ctx.profile, lunch_start=time(14)))
    result = replan_remaining_day(ctx, (system("lunch", 12, duration=60),))
    lunches = [item for item in result.plan.slots if item.kind == "lunch"]
    assert len(lunches) == 1 and lunches[0].interval == Interval(at(14), at(15))
    assert lunches[0].explanation


def test_missing_previous_lunch_does_not_create_a_new_slot_in_the_past() -> None:
    ctx = context(now=at(14))
    result = replan_remaining_day(ctx)
    assert not result.plan.slots and not result.changes


def test_without_previous_lunch_only_its_remaining_future_part_can_be_added() -> None:
    ctx = context(now=at(12, 30) + timedelta(microseconds=1))
    result = replan_remaining_day(ctx)
    assert result.plan.slots[0].interval == Interval(ctx.now, at(13))


def test_begun_break_is_protected_while_obsolete_future_breaks_disappear() -> None:
    started = system("break", 9, 50, 25)
    obsolete = system("break", 15)
    added = task(duration=15, preferred_start=time(10))
    result = replan_remaining_day(context(added), (started, obsolete))
    assert replace(started, preservation="system") in result.plan.slots
    assert obsolete not in result.plan.slots
    assert find_task(result.plan.slots, added.ref).interval.start >= at(10, 15)


def test_noncritical_day_removes_obsolete_future_rest_but_respects_explicit_reservations() -> None:
    rest = replace(system("rest", 15), preservation="system")
    assert not any(
        item.kind == "rest" for item in replan_remaining_day(context(), (rest,)).plan.slots
    )
    explicit = replan_remaining_day(context(fixed_slots=(rest,)), (rest,))
    assert rest in explicit.plan.slots


def test_critical_policy_counts_taken_rest_and_rebuilds_only_the_missing_block() -> None:
    taken, future_rest = system("rest", 8), system("rest", 15)
    result = replan_remaining_day(context(elapsed=644), (taken, future_rest))
    rests = [item for item in result.plan.slots if item.kind == "rest"]
    assert len(rests) == 2 and replace(taken, preservation="system") in rests
    assert sum(
        (item.interval.end - item.interval.start for item in rests), timedelta()
    ) == timedelta(hours=1)


def test_cross_day_moves_appear_in_the_diff_and_future_lunch_is_still_reserved() -> None:
    incoming = task(duration=60, kind="intellectual")
    future = FutureDay(DAY + timedelta(days=1))
    result = replan_remaining_day(
        context(incoming, elapsed=14, future_days=(future,)), (slot(incoming, 14),)
    )
    assert len(result.plan.moves) == len(result.changes) == 1
    change = result.changes[0]
    assert change.kind == "moved" and change.after is not None
    assert change.after.interval.start.date() == future.day
    assert "MOVED_FROM_CRITICAL_DAY" in change.reason_codes
    assert any(item.kind == "lunch" for item in result.plan.future_plans[0].slots)


def test_future_resident_tasks_are_not_reported_as_new_source_placements() -> None:
    day = DAY + timedelta(days=1)
    resident = task(10, planned_date=day)
    incoming = task(duration=60, kind="intellectual")
    ctx = context(incoming, elapsed=14, future_days=(FutureDay(day, (resident,)),))
    result = replan_remaining_day(ctx, (slot(incoming, 14),))
    assert [change.task for change in result.changes] == [incoming.ref]
    assert any(change.task == resident.ref for change in result.plan.future_plans[0].status_changes)


def test_task_that_no_longer_fits_is_reported_as_unplaced_and_removed_from_the_old_schedule() -> (
    None
):
    original = task()
    current = replace(original, duration_min=60)
    ctx = context(current, now=at(17))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(17, 45)))
    result = replan_remaining_day(ctx, (slot(original, 17, 30),))
    assert result.plan.unscheduled[0].task == current.ref
    assert (
        result.changes[0].kind == "removed"
        and "NO_FEASIBLE_INTERVAL" in result.changes[0].reason_codes
    )


@pytest.mark.parametrize("mode", ["initial", "preview"])
def test_remaining_day_adapter_rejects_other_modes(mode: str) -> None:
    with pytest.raises(ValueError, match="replan mode"):
        replan_remaining_day(context(mode=mode))


@pytest.mark.parametrize("problem", ["outside_day", "overlap", "duplicate_task", "draft_id"])
def test_invalid_previous_snapshot_is_rejected_even_if_its_future_tasks_were_deleted(
    problem: str,
) -> None:
    first, second = slot(task(), 14), slot(task(1), 15)
    expected = "FIXED_OUTSIDE_DAY"
    if problem == "outside_day":
        first = replace(
            first, interval=Interval(at(14) - timedelta(days=1), at(15) - timedelta(days=1))
        )
    elif problem == "overlap":
        second = replace(second, interval=Interval(at(14, 15), at(14, 45)))
        expected = "INTERVAL_OCCUPIED"
    elif problem == "duplicate_task":
        second = replace(second, task=first.task)
        expected = "TASK_ALREADY_RESERVED"
    else:
        first = replace(first, task=TaskRef(task_index=0))
        expected = "TASK_CONTEXT_MISMATCH"
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(), (first, second))
    assert caught.value.code == expected


def test_equivalent_explicit_fixed_and_previous_slots_are_deduplicated() -> None:
    item = task()
    old = slot(item, 8)
    ctx = context(item, fixed_slots=(replace(old, preservation="past"),))
    result = replan_remaining_day(ctx, (old,))
    assert sum(saved.task == item.ref for saved in result.plan.slots) == 1 and not result.changes


def test_conflicting_explicit_reservation_cannot_override_history() -> None:
    item = task()
    ctx = context(item, fixed_slots=(slot(item, 9, preservation="past"),))
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(ctx, (slot(item, 8),))
    assert caught.value.code == "FIXED_TASK_MISMATCH"


def test_past_day_does_not_duplicate_old_work_or_create_new_past_system_slots() -> None:
    old_task, added = task(), task(1)
    ctx = context(old_task, added, now=at(0) + timedelta(days=1))
    old = slot(old_task, 8)
    result = replan_remaining_day(ctx, (old,))
    assert result.plan.slots == (replace(old, preservation="past"),)
    assert result.plan.unscheduled[0].task == added.ref


def test_repeated_replan_is_stable_and_has_no_placement_diff_after_statuses_are_applied() -> None:
    old_task, added = task(), task(1)
    ctx = context(old_task, added)
    result = replan_remaining_day(ctx, (slot(old_task, 8),))
    applied = replace(ctx, tasks=tuple(replace(item, status="scheduled") for item in ctx.tasks))
    again = replan_remaining_day(applied, result.plan.slots)
    assert again.plan.slots == result.plan.slots
    assert not again.changes and not again.plan.status_changes


@given(st.lists(st.integers(5, 45), max_size=5))
@settings(max_examples=20, deadline=None)
def test_replanning_is_deterministic_and_accounts_for_every_current_task(
    durations: list[int],
) -> None:
    past = task(duration=30)
    items = tuple(task(i + 1, duration) for i, duration in enumerate(durations))
    ctx = context(past, *items)
    previous = (slot(past, 8),)
    result = replan_remaining_day(ctx, previous)
    assert result == replan_remaining_day(replace(ctx, tasks=ctx.tasks[::-1]), previous)
    plan = result.plan
    assigned = [item.task for item in plan.slots if item.task is not None]
    unplaced = [item.task for item in plan.unscheduled]
    assert len(set((*assigned, *unplaced))) == len(assigned) + len(unplaced) == len(ctx.tasks)
    assert set((*assigned, *unplaced)) == {item.ref for item in ctx.tasks}
    assert all(left.interval.end <= right.interval.start for left, right in pairwise(plan.slots))
    assert plan.metrics.requested_min == plan.metrics.planned_min + sum(
        item.duration_min for item in ctx.tasks if item.ref in unplaced
    )


@pytest.mark.parametrize("invalid", [None, 0, 1, "false"])
def test_lunch_generation_flag_is_strictly_boolean(invalid: Any) -> None:
    with pytest.raises(ValueError, match="boolean"):
        context(include_profile_lunch=invalid)


def test_placement_change_validates_its_identity_kind_and_actual_slots() -> None:
    item = task()
    old, new = slot(item, 13), slot(item, 14)
    with pytest.raises(ValueError, match="persisted"):
        PlacementChange(
            TaskRef(task_index=0), "added", None, replace(new, task=TaskRef(task_index=0))
        )
    with pytest.raises(ValueError, match="before or after"):
        PlacementChange(item.ref, "added", None, None)
    with pytest.raises(ValueError, match="reference"):
        PlacementChange(item.ref, "added", None, replace(new, task=task(1).ref))
    with pytest.raises(ValueError, match="actual change"):
        PlacementChange(item.ref, "updated", old, old)
    with pytest.raises(ValueError, match="kind"):
        PlacementChange(item.ref, "added", old, new)


def test_skipped_history_does_not_exhaust_the_intensity_budget_for_remaining_work() -> None:
    skipped = task(duration=220, kind="intellectual", status="skipped")
    added = task(1, 60, "intellectual")
    result = replan_remaining_day(context(skipped, added, now=at(12)), (slot(skipped, 8),))
    assert find_task(result.plan.slots, skipped.ref).interval.end == at(11, 40)
    assert find_task(result.plan.slots, added.ref).interval.start >= at(13)
    assert result.plan.metrics.high_intensity_min == result.plan.metrics.planned_min == 60
    assert result.plan.metrics.requested_min == 60 and not result.plan.unscheduled


@pytest.mark.parametrize("enabled", [False, True])
def test_disabled_profile_lunch_removes_future_lunch_but_preserves_taken_lunch(
    enabled: bool,
) -> None:
    ctx = context(include_profile_lunch=enabled)
    ctx = replace(ctx, profile=replace(ctx.profile, lunch_duration_min=0))
    assert not replan_remaining_day(ctx, (system("lunch", 12, duration=60),)).plan.slots
    taken = system("lunch", 8, duration=60)
    assert replace(taken, preservation="system") in replan_remaining_day(ctx, (taken,)).plan.slots


def test_dst_fold_preserves_elapsed_utc_history_even_when_local_clocks_repeat() -> None:
    day = date(2026, 10, 25)
    past = task(duration=30, planned_date=day)
    future_pin = task(1, planned_date=day, is_pinned=True, pinned_start=at(1, 30, day=day))
    old_past = replace(slot(past, 8), interval=Interval(at(0, 30, day=day), at(1, day=day)))
    old_future = replace(slot(future_pin, 8), interval=Interval(at(1, 30, day=day), at(2, day=day)))
    profile = replace(
        context().profile,
        birth_utc=at(12, day=day) - timedelta(days=2),
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_duration_min=0,
    )
    ctx = PlanContext(profile, day, at(1, 15, day=day), (past, future_pin), "replan")
    result = replan_remaining_day(ctx, (old_past, old_future))
    assert find_task(result.plan.slots, past.ref).preservation == "past"
    assert find_task(result.plan.slots, future_pin.ref).preservation == "pinned"
    assert not result.changes


def test_dst_gap_keeps_a_started_task_at_its_original_elapsed_duration() -> None:
    day = date(2026, 3, 29)
    started = task(duration=60, planned_date=day)
    added = task(1, 15, planned_date=day)
    old = replace(slot(started, 8), interval=Interval(at(0, 30, day=day), at(1, 30, day=day)))
    profile = replace(
        context().profile,
        birth_utc=at(12, day=day) - timedelta(days=2),
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(5),
        lunch_duration_min=0,
    )
    ctx = PlanContext(profile, day, at(1, day=day), (started, added), "replan")
    result = replan_remaining_day(ctx, (old,))
    assert find_task(result.plan.slots, started.ref).interval == old.interval
    assert find_task(result.plan.slots, added.ref).interval.start >= at(1, 30, day=day)


def test_utc_previous_date_is_still_history_of_the_current_local_day() -> None:
    item = task()
    start = at(20) - timedelta(days=1)
    old = replace(slot(item, 8), interval=Interval(start, start + timedelta(minutes=30)))
    ctx = context(item, now=at(21, 30) - timedelta(days=1))
    ctx = replace(ctx, profile=replace(ctx.profile, timezone="Asia/Yekaterinburg"))
    result = replan_remaining_day(ctx, (old,))
    assert find_task(result.plan.slots, item.ref).interval == old.interval
    assert find_task(result.plan.slots, item.ref).preservation == "past"


@pytest.mark.parametrize("old_hour", [None, 14])
def test_a_new_past_pin_is_not_mistaken_for_existing_history(old_hour: int | None) -> None:
    original = task()
    current = replace(original, is_pinned=True, pinned_start=at(8))
    previous = () if old_hour is None else (slot(original, old_hour),)
    with pytest.raises(ConstraintError) as caught:
        replan_remaining_day(context(current), previous)
    assert caught.value.code == "PAST_START"


@pytest.mark.parametrize("delta", [timedelta(), timedelta(microseconds=1)])
def test_a_new_pin_can_start_at_now_but_not_one_microsecond_before_it(delta: timedelta) -> None:
    item = task(is_pinned=True, pinned_start=at(10))
    ctx = context(item, now=at(10) + delta)
    if delta:
        with pytest.raises(ConstraintError) as caught:
            replan_remaining_day(ctx)
        assert caught.value.code == "PAST_START"
    else:
        assert find_task(replan_remaining_day(ctx).plan.slots, item.ref).interval.start == ctx.now


def test_an_explicit_saved_reservation_can_prove_that_a_past_pin_is_history() -> None:
    item = task(is_pinned=True, pinned_start=at(8))
    saved = slot(item, 8, preservation="pinned")
    result = replan_remaining_day(context(item, fixed_slots=(saved,)))
    assert saved in result.plan.slots


def test_skipped_placeholder_is_not_counted_as_an_actual_change_of_activity() -> None:
    items = tuple(
        task(i, 5, "intellectual", status="skipped" if i == 2 else "scheduled") for i in range(5)
    )
    previous = tuple(slot(item, 8 + i) for i, item in enumerate(items))
    result = replan_remaining_day(context(*items, now=at(14)), previous)
    assert any(warning.code == "ALTERNATING_TYPES" for warning in result.plan.warnings)
    assert result.plan.metrics.high_intensity_min == 20
