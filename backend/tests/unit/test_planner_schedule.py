from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.planner.constraints import ConstraintError, prepare_day, summarize_day
from app.modules.planner.contracts import (
    Interval,
    PlanContext,
    PlanMode,
    PlanProfile,
    PlanResult,
    PlanSlot,
    PlanTask,
    TaskKind,
    TaskRef,
)
from app.modules.planner.engine import build_schedule, sort_tasks

DAY = date(2026, 11, 14)
BEFORE_DAY = datetime(2026, 11, 13, tzinfo=UTC)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), UTC)


def task(index: int = 0, duration: int = 17, kind: TaskKind = "routine", **fields: Any) -> PlanTask:
    return replace(PlanTask(TaskRef(task_id=UUID(int=index + 1)), kind, duration, DAY), **fields)


def context(
    *tasks: PlanTask, fixed: tuple[PlanSlot, ...] = (), mode: PlanMode = "replan"
) -> PlanContext:
    profile = PlanProfile(
        # Neutral, positive cycles isolate placement from the stage-6 critical-day policy.
        datetime(2026, 11, 12, 12, tzinfo=UTC),
        "UTC",
        "dove",
        time(8),
        time(18),
        time(23),
    )
    return PlanContext(profile, DAY, BEFORE_DAY, tasks, mode, fixed)


def assert_invariants(ctx: PlanContext, result: PlanResult) -> None:
    by_ref = {item.ref: item for item in ctx.tasks}
    slots = result.slots
    assert slots == tuple(sorted(slots, key=lambda slot: slot.interval.start))
    assert all(left.interval.end <= right.interval.start for left, right in pairwise(slots))
    assigned = [slot.task for slot in slots if slot.task is not None]
    unassigned = [item.task for item in result.unscheduled]
    active = {item.ref for item in ctx.tasks if item.status != "skipped"}
    assert Counter((*assigned, *unassigned)) == Counter({ref: 1 for ref in active})
    assert result.moves == ()
    for slot in slots:
        if slot.task is not None:
            original = by_ref[slot.task]
            assert slot.interval.end - slot.interval.start == timedelta(
                minutes=original.duration_min
            )
            if slot.preservation is None:
                assert slot.interval.start >= ctx.now
                local = slot.interval.start.astimezone(ZoneInfo(ctx.profile.timezone))
                end = slot.interval.end.astimezone(local.tzinfo)
                assert ctx.profile.work_start <= local.time() < end.time() <= ctx.profile.work_end
    assert all(slot in slots for slot in ctx.fixed_slots)
    assert result.metrics.requested_min == sum(
        item.duration_min for item in ctx.tasks if item.status != "skipped"
    )
    assert result.metrics.planned_min == sum(by_ref[ref].duration_min for ref in assigned)
    assert result.metrics.planned_min <= result.metrics.requested_min


def test_empty_context_returns_a_valid_day_without_inventing_tasks() -> None:
    ctx = context()
    result = build_schedule(ctx)
    assert result.algorithm_version == "planner-1.0.1"
    assert result.metrics.planned_min == result.metrics.requested_min == 0
    assert result.metrics.capacity_min == 540
    assert [slot.kind for slot in result.slots] == ["lunch"]
    assert result.unscheduled == result.status_changes == ()
    assert_invariants(ctx, result)


def test_four_kinds_are_placed_as_whole_tasks_with_system_slots_and_status_proposals() -> None:
    tasks = tuple(
        task(index, 17, kind)
        for index, kind in enumerate(("intellectual", "physical", "creative", "routine"))
    )
    ctx = context(*tasks)
    result = build_schedule(ctx)
    assert not result.unscheduled
    assert result.metrics.planned_min == 68
    assert {change.task for change in result.status_changes} == {item.ref for item in tasks}
    assert all(
        change.previous == "pending" and change.next == "scheduled"
        for change in result.status_changes
    )
    assert all(item.status == "pending" for item in tasks)
    assert_invariants(ctx, result)


def test_task_order_resolves_priority_intensity_duration_creation_and_uuid() -> None:
    now = at(0)
    items = (
        task(0, 5, priority="high"),
        task(1, 120, "creative"),
        task(2, 5, "physical"),
        task(3, 60, "intellectual", created_at=now),
        task(4, 60, "physical", created_at=now - timedelta(minutes=1)),
        task(5, 60, "physical", created_at=now - timedelta(minutes=1)),
        task(6, 480, "intellectual", priority="low"),
    )
    assert sort_tasks(tuple(reversed(items))) == (
        items[0],
        items[4],
        items[5],
        items[3],
        items[2],
        items[1],
        items[6],
    )


def test_saved_uuid_with_missing_creation_time_has_a_stable_fallback() -> None:
    first, second = task(0, created_at=None), task(1, created_at=at(0))
    assert sort_tasks((second, first)) == (first, second)


def test_draft_ties_use_original_index_even_if_creation_values_are_present() -> None:
    first = replace(task(), ref=TaskRef(task_index=0), created_at=at(10))
    second = replace(task(1), ref=TaskRef(task_index=1), created_at=at(8))
    assert sort_tasks((second, first)) == (first, second)
    ctx = context(first, second, mode="preview")
    result = build_schedule(ctx)
    assert result.status_changes == ()
    assert_invariants(ctx, result)


def test_priority_claims_scarce_space_before_a_lower_priority_task() -> None:
    low = task(0, 30, priority="low")
    high = task(1, 30, priority="high")
    ctx = context(low, high)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(8, 30), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert [slot.task for slot in result.slots] == [high.ref]
    assert [item.task for item in result.unscheduled] == [low.ref]
    assert_invariants(ctx, result)


def test_too_large_high_priority_task_does_not_prevent_smaller_task_from_being_placed() -> None:
    large, small = task(0, 480, priority="high"), task(1, 17)
    ctx = context(large, small)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert [slot.task for slot in result.slots] == [small.ref]
    assert result.unscheduled[0].task == large.ref
    assert "NO_CONTIGUOUS_WINDOW" in result.unscheduled[0].reason_codes
    assert_invariants(ctx, result)


def test_negative_repetition_rating_does_not_discard_a_feasible_task() -> None:
    first, second = task(0, 5, "creative"), task(1, 5, "creative")
    ctx = context(first, second)
    ctx = replace(
        ctx,
        profile=replace(ctx.profile, work_start=time(2), work_end=time(3), lunch_duration_min=0),
    )
    result = build_schedule(ctx)
    assert not result.unscheduled
    assert [slot.interval.start for slot in result.slots] == [at(2), at(2, 15)]
    assert result.slots[1].score == -0.15
    assert "TYPE_REPETITION" in result.slots[1].reason_codes
    assert_invariants(ctx, result)


def test_neighbor_penalty_is_a_soft_preference_not_a_hard_rejection() -> None:
    first = task(0, 5, "creative", is_pinned=True, pinned_start=at(2))
    last = task(1, 5, "creative", is_pinned=True, pinned_start=at(2, 55))
    middle = task(2, 5, "creative")
    ctx = context(first, last, middle)
    ctx = replace(
        ctx,
        profile=replace(ctx.profile, work_start=time(2), work_end=time(3), lunch_duration_min=0),
    )
    result = build_schedule(ctx)
    chosen = next(slot for slot in result.slots if slot.task == middle.ref)
    assert chosen.score == -0.3
    assert not result.unscheduled
    assert_invariants(ctx, result)


def test_preferred_start_is_applied_to_actual_admissible_candidates() -> None:
    planned = task(0, 17, "creative", preferred_start=time(9))
    ctx = context(planned)
    result = build_schedule(ctx)
    slot = next(slot for slot in result.slots if slot.task is not None)
    assert at(8, 30) <= slot.interval.start <= at(9, 30)
    assert "PREFERRED_START" in slot.reason_codes
    assert_invariants(ctx, result)


def test_preview_has_no_status_changes_and_every_draft_is_accounted_for() -> None:
    tasks = tuple(replace(task(index, 480), ref=TaskRef(task_index=index)) for index in range(3))
    ctx = context(*tasks, mode="preview")
    result = build_schedule(ctx)
    assert result.unscheduled and result.status_changes == ()
    assert_invariants(ctx, result)


def test_initial_mode_returns_partial_result_for_the_completion_adapter_to_reject() -> None:
    ctx = replace(context(task(0, 480), task(1, 480)), mode="initial")
    result = build_schedule(ctx)
    assert result.unscheduled
    assert_invariants(ctx, result)


def test_fixed_pins_done_and_started_slots_survive_with_original_metadata() -> None:
    done = task(0, 17, status="done")
    started = task(1, 60, status="scheduled")
    pinned = task(2, 17, is_pinned=True, pinned_start=at(13, 7))
    new = task(3, 17)
    saved = (
        PlanSlot(
            "task",
            Interval(at(7), at(7, 17)),
            task=done.ref,
            preservation="done",
            explanation="Сохранённая история",
        ),
        PlanSlot(
            "task", Interval(at(9), at(10)), task=started.ref, preservation="started", score=0.6
        ),
    )
    ctx = replace(context(done, started, pinned, new, fixed=saved), now=at(9, 30))
    result = build_schedule(ctx)
    assert all(slot in result.slots for slot in saved)
    pin_slot = next(slot for slot in result.slots if slot.task == pinned.ref)
    assert pin_slot.interval == Interval(at(13, 7), at(13, 24))
    assert all(change.task not in {done.ref, started.ref} for change in result.status_changes)
    assert_invariants(ctx, result)


def test_done_only_retains_derived_breaks_without_any_new_placement() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    second = task(1, 60, "intellectual", is_pinned=True, pinned_start=at(9, 30))
    ctx = context(first, second)
    result = build_schedule(ctx)
    assert [(slot.kind, slot.interval, slot.task) for slot in result.slots] == [
        (slot.kind, slot.interval, slot.task) for slot in prepare_day(ctx).slots
    ]
    assert all(slot.explanation for slot in result.slots)
    assert any(slot.kind == "break" for slot in result.slots)
    assert result.metrics.capacity_min == 510


def test_skipped_task_is_excluded_from_placement_and_requested_metrics() -> None:
    skipped, active = task(0, 480, status="skipped"), task(1, 17)
    ctx = context(skipped, active)
    result = build_schedule(ctx)
    assert result.metrics.requested_min == 17
    assert all(change.task != skipped.ref for change in result.status_changes)
    assert_invariants(ctx, result)


def test_unplaced_scheduled_task_proposes_pending_without_mutating_original() -> None:
    planned = task(status="scheduled", deadline=DAY - timedelta(days=1))
    ctx = context(planned)
    result = build_schedule(ctx)
    assert result.unscheduled[0].task == planned.ref
    assert "DEADLINE_EXCEEDED" in result.unscheduled[0].reason_codes
    assert len(result.status_changes) == 1
    assert (
        result.status_changes[0].previous == "scheduled"
        and result.status_changes[0].next == "pending"
    )
    assert planned.status == "scheduled"
    assert_invariants(ctx, result)


def test_existing_scheduled_task_that_fits_has_no_redundant_status_proposal() -> None:
    result = build_schedule(context(task(status="scheduled")))
    assert not result.status_changes and not result.unscheduled


def test_past_day_reports_no_available_time_without_inventing_history() -> None:
    ctx = replace(context(task()), now=at(20))
    result = build_schedule(ctx)
    assert not any(slot.kind == "task" for slot in result.slots)
    assert "NO_AVAILABLE_TIME" in result.unscheduled[0].reason_codes
    assert_invariants(ctx, result)


def test_unscheduled_records_include_observed_budget_and_overlap_causes() -> None:
    first, second = task(0, 240, "physical"), task(1, 240, "physical")
    ctx = context(first, second)
    result = build_schedule(ctx)
    assert result.unscheduled
    reasons = result.unscheduled[0].reason_codes
    assert reasons[0] == "NO_FEASIBLE_INTERVAL"
    assert "INTENSITY_CAPACITY_EXCEEDED" in reasons and "INTERVAL_OCCUPIED" in reasons
    assert_invariants(ctx, result)


def test_explicit_rest_and_load_factor_are_applied_to_the_final_metrics() -> None:
    ctx = context(task())
    rest = (Interval(at(9), at(9, 30)),)
    result = build_schedule(ctx, load_factor=0.5, rest_intervals=rest)
    assert result.metrics.load_factor == 0.5
    assert result.metrics.capacity_min == 255
    assert any(slot.kind == "rest" and slot.interval == rest[0] for slot in result.slots)
    assert_invariants(ctx, result)


def test_greedy_placement_replaces_derived_breaks_instead_of_duplicating_them() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    last = task(1, 60, "intellectual", is_pinned=True, pinned_start=at(10))
    middle = task(2, 30, preferred_start=time(9))
    ctx = context(first, last, middle)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(11), lunch_duration_min=0))
    result = build_schedule(ctx)
    slot = next(slot for slot in result.slots if slot.task == middle.ref)
    assert at(9) <= slot.interval.start < at(10)
    assert not any(slot.kind == "break" for slot in result.slots)
    assert result.metrics.capacity_min == 180
    assert_invariants(ctx, result)


def test_conflicting_fixed_input_fails_instead_of_returning_a_fake_success() -> None:
    first = task(0, 60, is_pinned=True, pinned_start=at(8))
    second = task(1, 60, is_pinned=True, pinned_start=at(8, 30))
    with pytest.raises(ConstraintError):
        build_schedule(context(first, second))


@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"])
def test_profile_timezone_is_used_for_placement_and_result(zone: str) -> None:
    ctx = context(task())
    ctx = replace(ctx, profile=replace(ctx.profile, timezone=zone))
    result = build_schedule(ctx)
    assert result.timezone == zone
    assert_invariants(ctx, result)


def test_daylight_saving_day_keeps_utc_intervals_and_preview_local_clocks_unambiguous() -> None:
    ctx = context(task(0, 17), task(1, 17))
    day = date(2026, 10, 25)
    tasks = tuple(
        replace(item, planned_date=day, ref=TaskRef(task_index=index))
        for index, item in enumerate(ctx.tasks)
    )
    profile = replace(
        ctx.profile,
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_duration_min=0,
    )
    ctx = PlanContext(profile, day, datetime(1900, 1, 1, tzinfo=UTC), tasks, "preview")
    result = build_schedule(ctx)
    assert not result.unscheduled
    assert result.metrics.capacity_min == 300
    assert_invariants(ctx, result)


def test_summarize_day_can_use_baseline_breaks_and_rejects_invalid_critical_level() -> None:
    prepared = prepare_day(context())
    assert summarize_day(prepared).capacity_min == 540
    for invalid in (-1, 4, True):
        with pytest.raises(ValueError, match="critical_level"):
            summarize_day(prepared, critical_level=invalid)


@given(data=st.data(), durations=st.lists(st.integers(5, 75), min_size=0, max_size=7))
@settings(max_examples=30, deadline=None)
def test_property_result_is_invariant_under_task_input_permutations_and_loses_nothing(
    data: st.DataObject, durations: list[int]
) -> None:
    kinds: tuple[TaskKind, ...] = ("intellectual", "physical", "creative", "routine")
    tasks = tuple(
        task(index, duration, kinds[index % 4]) for index, duration in enumerate(durations)
    )
    shuffled = tuple(data.draw(st.permutations(tasks)))
    ctx = context(*tasks)
    first = build_schedule(ctx)
    assert first == build_schedule(replace(ctx, tasks=shuffled)) == build_schedule(ctx)
    assert_invariants(ctx, first)
