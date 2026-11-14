from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.planner.constraints import (
    ConstraintError,
    check_placement,
    feasible_intervals,
    overlaps,
    prepare_day,
    required_break_minutes,
)
from app.modules.planner.contracts import (
    Interval,
    PlanContext,
    PlanProfile,
    PlanSlot,
    PlanTask,
    TaskKind,
    TaskRef,
)
from app.modules.planner.energy import score_interval
from app.modules.planner.engine import PlannerTimeError

DAY = date(2026, 11, 14)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), UTC)


def interval(start: int, end: int) -> Interval:
    return Interval(at(start), at(end))


def task(index: int = 0, duration: int = 60, kind: TaskKind = "routine", **fields: Any) -> PlanTask:
    return replace(PlanTask(TaskRef(task_id=UUID(int=index + 1)), kind, duration, DAY), **fields)


def context(
    *tasks: PlanTask, now: datetime | None = None, fixed: tuple[PlanSlot, ...] = ()
) -> PlanContext:
    profile = PlanProfile(at(0) - timedelta(days=1000), "UTC", "dove", time(8), time(18), time(23))
    return PlanContext(profile, DAY, now or at(0), tasks, "replan", fixed)


def fixed_slot(task: PlanTask, span: Interval, preservation: str = "pinned") -> PlanSlot:
    return PlanSlot(
        "task",
        span,
        task=task.ref,
        is_pinned=task.is_pinned,
        preservation=preservation,
        score=0.7,
        explanation="Сохранённое размещение",
        reason_codes=("SAVED",),
    )


def test_lunch_and_baseline_capacity_are_deterministic_without_fifteen_percent_deduction() -> None:
    ctx = context(task())
    day = prepare_day(ctx)
    assert day == prepare_day(ctx)
    assert day.capacity_min == 540 and day.high_intensity_cap_min == 240
    assert day.reserved_task_min == day.reserved_high_intensity_min == 0
    assert [(slot.kind, slot.interval) for slot in day.reserved_slots] == [
        ("lunch", interval(12, 13))
    ]
    assert ctx.fixed_slots == ()
    assert not day.over_capacity and not day.over_intensity_limit


@pytest.mark.parametrize(
    ("start", "end", "lunch_minutes", "expected"),
    [
        (time(12, 30), time(14), 60, 60),
        (time(8), time(12), 60, 240),
        (time(13), time(18), 60, 300),
        (time(8), time(18), 0, 600),
    ],
)
def test_lunch_is_clipped_to_work_window_or_disabled(
    start: time, end: time, lunch_minutes: int, expected: int
) -> None:
    ctx = context()
    ctx = replace(
        ctx,
        profile=replace(
            ctx.profile, work_start=start, work_end=end, lunch_duration_min=lunch_minutes
        ),
    )
    assert prepare_day(ctx).capacity_min == expected


@pytest.mark.parametrize(
    ("factor", "capacity", "intensity"),
    [(1, 540, 240), (0.8, 432, 192), (0.65, 351, 156), (0.5, 270, 120), (0.45, 243, 108)],
)
def test_capacity_scales_with_decimal_rounding(
    factor: float, capacity: int, intensity: int
) -> None:
    day = prepare_day(context(), load_factor=factor)
    assert day.capacity_min == capacity and day.high_intensity_cap_min == intensity


@pytest.mark.parametrize("factor", [0, -1, 1.1, True, float("nan"), float("inf")])
def test_invalid_load_factor_is_not_accepted(factor: float) -> None:
    with pytest.raises(ValueError, match="load_factor"):
        prepare_day(context(), load_factor=factor)


def test_saved_lunch_is_preserved_without_duplicate_reservation() -> None:
    lunch = PlanSlot("lunch", interval(12, 13), preservation="system", explanation="Исходный обед")
    day = prepare_day(context(fixed=(lunch,)))
    assert day.reserved_slots == (lunch,)
    assert day.capacity_min == 540


def test_explicit_rest_is_counted_once_and_can_be_supplied_to_a_later_critical_day_policy() -> None:
    rest = PlanSlot("rest", Interval(at(9), at(9, 30)), preservation="system")
    day = prepare_day(
        context(fixed=(rest,)),
        rest_intervals=(rest.interval, Interval(at(10), at(10, 30))),
        load_factor=0.5,
    )
    assert day.capacity_min == 240
    assert len([slot for slot in day.reserved_slots if slot.kind == "rest"]) == 2


@pytest.mark.parametrize(
    "span", [Interval(at(7), at(8)), Interval(at(17, 30), at(18, 30)), Interval(at(8), at(8, 30))]
)
def test_new_rest_must_fit_future_work_window(span: Interval) -> None:
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(now=at(9)), rest_intervals=(span,))
    assert error.value.code == "INVALID_REST_INTERVAL"


def test_pinned_task_outside_grid_is_preserved_exactly() -> None:
    pinned = task(0, 17, is_pinned=True, pinned_start=at(8, 7))
    other = task(1, 17)
    day = prepare_day(context(pinned, other))
    slot = next(slot for slot in day.reserved_slots if slot.task == pinned.ref)
    assert slot.interval == Interval(at(8, 7), at(8, 24)) and slot.is_pinned
    candidates = feasible_intervals(day, other)
    assert candidates[0].start == at(8, 30)
    assert all(not overlaps(slot.interval, candidate) for candidate in candidates)
    assert check_placement(day, pinned, slot.interval).reasons == (
        "TASK_ALREADY_RESERVED",
        "INTERVAL_OCCUPIED",
    )


@pytest.mark.parametrize(
    ("start", "deadline", "code"),
    [
        (at(19), None, "OUTSIDE_WORK_WINDOW"),
        (at(8), DAY - timedelta(days=1), "DEADLINE_EXCEEDED"),
        (at(8) + timedelta(days=1), None, "FIXED_OUTSIDE_DAY"),
        (datetime.max.replace(tzinfo=UTC), None, "FIXED_OUTSIDE_DAY"),
        (at(23, 59), None, "FIXED_OUTSIDE_DAY"),
    ],
)
def test_invalid_new_pin_is_rejected_without_modifying_the_task(
    start: datetime, deadline: date | None, code: str
) -> None:
    pinned = task(is_pinned=True, pinned_start=start, deadline=deadline)
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(pinned))
    assert error.value.code == code and pinned.pinned_start == start


def test_pin_conflicting_with_lunch_is_rejected() -> None:
    pinned = task(duration=30, is_pinned=True, pinned_start=at(12))
    with pytest.raises(ConstraintError, match="пересекаются") as error:
        prepare_day(context(pinned))
    assert error.value.code == "INTERVAL_OCCUPIED"


def test_conflicting_pins_are_not_moved_to_resolve_the_conflict() -> None:
    first = task(0, is_pinned=True, pinned_start=at(8))
    second = task(1, is_pinned=True, pinned_start=at(8, 30))
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(first, second))
    assert error.value.code == "INTERVAL_OCCUPIED"
    assert second.pinned_start == at(8, 30)


def test_done_task_requires_the_authoritative_saved_interval() -> None:
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(task(status="done")))
    assert error.value.code == "FIXED_SLOT_REQUIRED"


def test_done_history_outside_new_work_window_survives_and_is_not_rescheduled() -> None:
    done = task(status="done")
    saved = fixed_slot(done, interval(5, 6), "done")
    day = prepare_day(context(done, now=at(10), fixed=(saved,)))
    assert saved in day.reserved_slots and day.reserved_task_min == 60
    assert feasible_intervals(day, done) == ()


def test_started_task_is_preserved_and_blocks_candidates_until_its_end() -> None:
    started = task(status="scheduled")
    new = task(1, 17)
    saved = fixed_slot(started, interval(9, 10), "started")
    day = prepare_day(context(started, new, now=at(9, 30), fixed=(saved,)))
    assert saved in day.reserved_slots
    assert "INTERVAL_OCCUPIED" in check_placement(day, new, Interval(at(9, 45), at(10, 2))).reasons
    assert feasible_intervals(day, new)[0].start == at(10)


@pytest.mark.parametrize(
    ("status", "preservation", "span", "now"),
    [
        ("pending", "done", interval(8, 9), at(10)),
        ("pending", "started", interval(10, 11), at(9)),
        ("pending", "past", interval(10, 11), at(10)),
        ("pending", "pinned", interval(8, 9), at(0)),
        ("skipped", "past", interval(8, 9), at(10)),
    ],
)
def test_inconsistent_saved_state_is_reported(
    status: Any, preservation: Any, span: Interval, now: datetime
) -> None:
    planned = task(status=status)
    saved = fixed_slot(planned, span, preservation)
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(planned, now=now, fixed=(saved,)))
    assert error.value.code == "FIXED_TASK_MISMATCH"


def test_fixed_task_duration_and_pin_metadata_must_match_snapshot() -> None:
    planned = task(is_pinned=True, pinned_start=at(8))
    for saved in (
        fixed_slot(planned, Interval(at(8), at(8, 30))),
        replace(fixed_slot(planned, interval(8, 9)), is_pinned=False),
    ):
        with pytest.raises(ConstraintError) as error:
            prepare_day(context(planned, fixed=(saved,)))
        assert error.value.code == "FIXED_TASK_MISMATCH"


def test_existing_over_budget_pin_survives_but_new_work_cannot_increase_overload() -> None:
    pinned = task(0, 300, is_pinned=True, pinned_start=at(13))
    other = task(1, 5)
    day = prepare_day(context(pinned, other), load_factor=0.5)
    assert day.over_capacity and day.reserved_task_min == 300
    result = check_placement(day, other, Interval(at(8), at(8, 5)))
    assert result.reasons == ("DAY_CAPACITY_EXCEEDED",)


def test_exhausted_intensity_budget_still_allows_non_intensive_work() -> None:
    pinned = task(0, 241, "physical", is_pinned=True, pinned_start=at(13))
    routine = task(1, 5)
    intense = task(2, 5, "physical")
    day = prepare_day(context(pinned, routine, intense))
    assert day.over_intensity_limit
    assert check_placement(day, routine, Interval(at(8), at(8, 5))).allowed
    assert check_placement(day, intense, Interval(at(8), at(8, 5))).reasons == (
        "INTENSITY_CAPACITY_EXCEEDED",
    )


@pytest.mark.parametrize(
    ("left_kind", "right_kind", "duration", "continuous", "expected"),
    [
        ("routine", "routine", 90, 90, 0),
        ("routine", "routine", 91, 91, 15),
        ("routine", "routine", 120, 120, 15),
        ("routine", "routine", 121, 121, 30),
        ("physical", "intellectual", 60, 60, 10),
        ("intellectual", "intellectual", 15, 15, 30),
    ],
)
def test_break_rules_use_maximum_and_do_not_split_long_tasks(
    left_kind: TaskKind, right_kind: TaskKind, duration: int, continuous: int, expected: int
) -> None:
    assert (
        required_break_minutes(task(0, duration, left_kind), task(1, 15, right_kind), continuous)
        == expected
    )


def test_continuous_counter_cannot_be_negative_boolean_or_shorter_than_last_task() -> None:
    for value in (True, 59, -1):
        with pytest.raises(ValueError):
            required_break_minutes(task(), task(1), value)


def test_two_intellectual_tasks_require_thirty_minutes_before_placement() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    second = task(1, 60, "intellectual")
    day = prepare_day(context(first, second))
    assert check_placement(day, second, Interval(at(9, 15), at(10, 15))).reasons == (
        "INSUFFICIENT_BREAK",
    )
    check = check_placement(day, second, Interval(at(9, 30), at(10, 30)))
    assert check.allowed
    assert [slot.interval for slot in check.required_breaks] == [Interval(at(9), at(9, 30))]


def test_fixed_future_tasks_reserve_their_required_break_in_advance() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    second = task(1, 60, "intellectual", is_pinned=True, pinned_start=at(9, 30))
    day = prepare_day(context(first, second))
    assert [slot.interval for slot in day.slots if slot.kind == "break"] == [
        Interval(at(9), at(9, 30))
    ]
    assert day.capacity_min == 510
    with pytest.raises(ConstraintError) as error:
        prepare_day(context(first, replace(second, pinned_start=at(9, 15))))
    assert error.value.code == "INSUFFICIENT_BREAK"


def test_long_last_task_does_not_need_a_fictitious_break_after_end_of_work() -> None:
    long = task(0, 180)
    ctx = context(long)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(11), lunch_duration_min=0))
    result = check_placement(prepare_day(ctx), long, interval(8, 11))
    assert result.allowed and not result.required_breaks


def test_short_idle_gap_does_not_reset_accumulated_continuous_work() -> None:
    first = task(0, 60, is_pinned=True, pinned_start=at(8))
    second, third = task(1, 60), task(2, 17)
    day = prepare_day(context(first, second, third))
    placed = (PlanSlot("task", interval(9, 10), task=second.ref),)
    assert check_placement(
        day, third, Interval(at(10), at(10, 17)), placed_slots=placed
    ).reasons == ("INSUFFICIENT_BREAK",)
    check = check_placement(day, third, Interval(at(10, 15), at(10, 32)), placed_slots=placed)
    assert check.allowed and check.required_breaks[0].interval == Interval(at(10), at(10, 15))


def test_insertion_before_fixed_task_checks_its_following_break_as_well() -> None:
    fixed = task(0, 30, "creative", is_pinned=True, pinned_start=at(10))
    new = task(1, 110)
    day = prepare_day(context(fixed, new))
    assert check_placement(day, new, Interval(at(8), at(9, 50))).reasons == ("INSUFFICIENT_BREAK",)


def test_lunch_satisfies_required_rest_without_duplicate_subtraction() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(11))
    second = task(1, 60, "intellectual")
    day = prepare_day(context(first, second))
    check = check_placement(day, second, interval(13, 14))
    assert check.allowed and check.required_breaks == () and day.capacity_min == 540


def test_partial_existing_rest_only_creates_uncovered_break_pieces() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    second = task(1, 60, "intellectual")
    rest = Interval(at(9, 10), at(9, 20))
    day = prepare_day(context(first, second), rest_intervals=(rest,))
    check = check_placement(day, second, Interval(at(9, 30), at(10, 30)))
    assert check.allowed
    assert [slot.interval for slot in check.required_breaks] == [
        Interval(at(9), at(9, 10)),
        Interval(at(9, 20), at(9, 30)),
    ]
    assert all(not overlaps(slot.interval, rest) for slot in check.required_breaks)


def test_inserting_task_checks_day_budget_after_new_breaks_are_reserved() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    second = task(1, 60, "intellectual")
    ctx = context(first, second)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10, 30), lunch_duration_min=0))
    assert check_placement(prepare_day(ctx), second, Interval(at(9, 30), at(10, 30))).allowed
    rejected = check_placement(
        prepare_day(ctx, load_factor=0.9), second, Interval(at(9, 30), at(10, 30))
    )
    assert rejected.reasons == ("DAY_CAPACITY_EXCEEDED",) and rejected.required_breaks == ()


def test_placement_rejections_report_hard_constraints_before_energy_ranking() -> None:
    planned = task(duration=17, deadline=DAY - timedelta(days=1))
    day = prepare_day(context(planned, now=at(9)))
    reasons = check_placement(day, planned, Interval(at(7), at(7, 15))).reasons
    assert reasons == (
        "DURATION_MISMATCH",
        "OUTSIDE_WORK_WINDOW",
        "PAST_START",
        "DEADLINE_EXCEEDED",
    )
    assert feasible_intervals(day, planned) == ()


def test_touching_non_intensive_tasks_are_allowed_and_deadline_date_is_inclusive() -> None:
    first = task(0, is_pinned=True, pinned_start=at(8))
    second = task(1, deadline=DAY)
    day = prepare_day(context(first, second))
    assert check_placement(day, second, interval(9, 10)).allowed
    assert not overlaps(interval(8, 9), interval(9, 10))


def test_unknown_task_and_invalid_placed_slots_are_not_silently_accepted() -> None:
    planned = task()
    day = prepare_day(context(planned))
    with pytest.raises(ConstraintError) as error:
        check_placement(day, task(1), interval(8, 9))
    assert error.value.code == "TASK_CONTEXT_MISMATCH"
    with pytest.raises(ConstraintError):
        feasible_intervals(day, task(1))
    placed = PlanSlot("task", interval(8, 9), task=planned.ref)
    with pytest.raises(ConstraintError) as error:
        check_placement(day, planned, interval(9, 10), placed_slots=(placed, placed))
    assert error.value.code == "TASK_ALREADY_RESERVED"


@pytest.mark.parametrize(
    ("date", "window_minutes"), [(date(2026, 3, 29), 180), (date(2026, 10, 25), 300)]
)
def test_lunch_duration_and_capacity_use_elapsed_minutes_across_dst(
    date: date, window_minutes: int
) -> None:
    ctx = context()
    profile = replace(
        ctx.profile,
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_start=time(1, 30),
    )
    ctx = replace(ctx, day=date, now=datetime(1900, 1, 1, tzinfo=UTC), profile=profile)
    day = prepare_day(ctx)
    lunch = next(slot for slot in day.reserved_slots if slot.kind == "lunch")
    assert lunch.interval.end - lunch.interval.start == timedelta(minutes=60)
    assert day.capacity_min == window_minutes - 60


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
def test_lunch_start_does_not_guess_missing_or_repeated_time(day: date) -> None:
    ctx = context()
    profile = replace(
        ctx.profile,
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_start=time(2, 30),
    )
    with pytest.raises(PlannerTimeError) as error:
        prepare_day(replace(ctx, day=day, now=datetime(1900, 1, 1, tzinfo=UTC), profile=profile))
    assert error.value.field == "lunch_start"


def test_stages_one_to_four_rank_only_feasible_exact_duration_candidates() -> None:
    pin = task(0, 60, is_pinned=True, pinned_start=at(10))
    new = task(1, 17, "intellectual", preferred_start=time(10))
    day = prepare_day(context(pin, new))
    candidates = feasible_intervals(day, new)
    best = max(candidates, key=lambda value: score_interval(day.context.profile, new, value).total)
    assert check_placement(day, new, best).allowed
    assert best.end - best.start == timedelta(minutes=17)
    assert all(not overlaps(best, reserved.interval) for reserved in day.reserved_slots)


@given(
    duration=st.integers(5, 240),
    minute=st.integers(8 * 60, 17 * 60),
    factor=st.sampled_from([1.0, 0.8, 0.65, 0.5]),
)
def test_property_admitted_interval_respects_reserved_time_and_budgets(
    duration: int, minute: int, factor: float
) -> None:
    pin = task(0, 17, is_pinned=True, pinned_start=at(8, 7))
    new = task(1, duration, "physical")
    day = prepare_day(context(pin, new), load_factor=factor)
    start = at(0) + timedelta(minutes=minute)
    candidate = Interval(start, start + timedelta(minutes=duration))
    check = check_placement(day, new, candidate)
    if check.allowed:
        assert at(8) <= candidate.start < candidate.end <= at(18)
        assert all(not overlaps(candidate, slot.interval) for slot in day.reserved_slots)
        assert duration <= day.high_intensity_cap_min
        assert duration + 17 <= day.capacity_min
        assert all(not overlaps(candidate, slot.interval) for slot in check.required_breaks)


def test_skipped_task_has_no_reserved_slot_and_cannot_be_placed() -> None:
    skipped = task(status="skipped", is_pinned=True, pinned_start=at(8))
    day = prepare_day(context(skipped))
    assert not any(slot.task == skipped.ref for slot in day.reserved_slots)
    assert check_placement(day, skipped, interval(8, 9)).reasons == ("TASK_INACTIVE",)


def test_intensive_gap_is_ten_real_minutes_not_rounded_to_the_search_grid() -> None:
    first = task(0, 45, "physical", is_pinned=True, pinned_start=at(8))
    second = task(1, 5, "physical")
    day = prepare_day(context(first, second))
    assert check_placement(day, second, Interval(at(8, 54), at(8, 59))).reasons == (
        "INSUFFICIENT_BREAK",
    )
    check = check_placement(day, second, Interval(at(8, 55), at(9)))
    assert check.allowed and check.required_breaks[0].interval == Interval(at(8, 45), at(8, 55))


def test_rest_already_elapsed_after_history_does_not_create_a_break_in_the_past() -> None:
    done = task(0, 60, "intellectual", status="done")
    new = task(1, 60, "intellectual")
    saved = fixed_slot(done, interval(8, 9), "done")
    day = prepare_day(context(done, new, now=at(10), fixed=(saved,)))
    check = check_placement(day, new, interval(11, 12))
    assert check.allowed and not check.required_breaks


def test_history_outside_work_window_does_not_create_new_system_slots_outside_it() -> None:
    done = task(0, 121, status="done")
    new = task(1, 17)
    saved = fixed_slot(done, Interval(at(3, 59), at(6)), "done")
    day = prepare_day(context(done, new, now=at(5), fixed=(saved,)))
    check = check_placement(day, new, Interval(at(8), at(8, 17)))
    assert check.allowed and not check.required_breaks


def test_invalid_builder_state_fails_before_it_can_corrupt_the_plan() -> None:
    planned = task()
    day = prepare_day(context(planned, now=at(10)))
    for placed, expected in (
        (PlanSlot("task", interval(11, 12), task=task(1).ref), "TASK_CONTEXT_MISMATCH"),
        (PlanSlot("task", interval(8, 9), task=planned.ref), "PAST_START"),
        (
            PlanSlot("task", interval(11, 12), task=planned.ref, preservation="system"),
            "FIXED_TASK_MISMATCH",
        ),
    ):
        with pytest.raises(ConstraintError) as error:
            check_placement(day, planned, interval(13, 14), placed_slots=(placed,))
        assert error.value.code == expected


def test_capacity_rounds_only_after_subtracting_fractional_minutes_and_scaling() -> None:
    ctx = context()
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(8, 2), lunch_duration_min=0))
    rest = PlanSlot("rest", Interval(at(8), at(8) + timedelta(seconds=6)), preservation="system")
    day = prepare_day(replace(ctx, fixed_slots=(rest,)), load_factor=0.8)
    assert day.capacity_min == 1  # (120 - 6) seconds / 60 * .8 = 1.52 minutes.


def test_historical_deadline_is_not_reinterpreted_to_reject_completed_work() -> None:
    done = task(status="done", deadline=date.max)
    saved = fixed_slot(done, interval(8, 9), "done")
    day = prepare_day(context(done, now=at(10), fixed=(saved,)))
    assert saved in day.reserved_slots
    assert feasible_intervals(day, done) == ()


def test_derived_breaks_can_change_when_another_task_is_inserted_between_fixed_tasks() -> None:
    first = task(0, 60, "intellectual", is_pinned=True, pinned_start=at(8))
    last = task(1, 60, "intellectual", is_pinned=True, pinned_start=at(10))
    middle = task(2, 30)
    day = prepare_day(context(first, last, middle))
    assert day.required_breaks[0].interval == Interval(at(9), at(9, 30))
    result = check_placement(day, middle, Interval(at(9), at(9, 30)))
    assert result.allowed and result.required_breaks == ()
    assert day.required_breaks[0].interval == Interval(at(9), at(9, 30))
