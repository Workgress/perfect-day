from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.modules.biorhythm.types import Cycle
from app.modules.planner.contracts import (
    FutureDay,
    Interval,
    PlanContext,
    PlanProfile,
    PlanSlot,
    PlanTask,
    TaskKind,
    TaskRef,
)
from app.modules.planner.engine import build_schedule
from app.modules.planner.policy import day_policy, prepare_policy_day
from app.modules.planner.time_grid import PlannerTimeError

DAY = date(2026, 11, 14)


def at(hour: int, minute: int = 0, *, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def task(
    index: int = 0, duration: int = 60, kind: TaskKind = "intellectual", **kw: Any
) -> PlanTask:
    return replace(PlanTask(TaskRef(task_id=UUID(int=index + 1)), kind, duration, DAY), **kw)


def context(*tasks: PlanTask, elapsed: float = 2, **kw: Any) -> PlanContext:
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
    return replace(PlanContext(profile, DAY, at(0) - timedelta(days=1), tasks, mode), **kw)


def future(offset: int = 1, *tasks: PlanTask, fixed: tuple[PlanSlot, ...] = ()) -> FutureDay:
    day = DAY + timedelta(days=offset)
    return FutureDay(day, tuple(replace(item, planned_date=day) for item in tasks), fixed)


@pytest.mark.parametrize(
    ("elapsed", "level", "factor", "rests", "capacity"),
    [
        (2, 0, 1.0, 0, 540),
        (11.5, 1, 0.8, 0, 432),
        (14, 1, 0.72, 0, 388),
        (23, 1, 0.72, 0, 388),  # two minima still apply only one 0.9 multiplier
        (966, 2, 0.65, 1, 331),
        (322, 2, 0.585, 1, 298),
        (644, 3, 0.5, 2, 240),
        (20, 0, 0.9, 0, 486),
    ],
)
def test_real_cycle_crossings_drive_capacity_once(
    elapsed: float, level: int, factor: float, rests: int, capacity: int
) -> None:
    ctx = context(elapsed=elapsed)
    policy = day_policy(ctx.profile, DAY)
    result = build_schedule(ctx)
    assert policy.critical.level == result.metrics.critical_level == level
    assert policy.load_factor == result.metrics.load_factor == factor
    assert result.metrics.capacity_min == capacity
    assert sum(slot.kind == "rest" for slot in result.slots) == rests
    assert all(
        slot.interval.end - slot.interval.start == timedelta(minutes=30)
        for slot in result.slots
        if slot.kind == "rest"
    )
    assert all(slot.explanation for slot in result.slots)
    assert any(w.code == "CRITICAL_DAY" for w in result.warnings) == bool(level)


def test_intensity_cap_uses_the_same_factor_and_floor_as_total_capacity() -> None:
    ctx = context(task(duration=141), elapsed=322)
    prepared, shortfall = prepare_policy_day(ctx, day_policy(ctx.profile, DAY))
    assert shortfall == 0 and prepared.high_intensity_cap_min == 140
    result = build_schedule(ctx)
    assert "INTENSITY_CAPACITY_EXCEEDED" in result.unscheduled[0].reason_codes


def test_explicit_factor_override_does_not_disable_mandatory_rest() -> None:
    result = build_schedule(context(elapsed=644), load_factor=0.8)
    assert result.metrics.capacity_min == 384
    assert sum(slot.kind == "rest" for slot in result.slots) == 2


def test_existing_rest_is_preserved_and_not_counted_twice() -> None:
    rest = PlanSlot(
        "rest", Interval(at(9), at(9, 30)), preservation="system", explanation="Сохранённый отдых"
    )
    ctx = context(elapsed=644, fixed_slots=(rest,))
    result = build_schedule(ctx)
    assert rest in result.slots
    assert sum(slot.kind == "rest" for slot in result.slots) == 2
    assert result.metrics.capacity_min == 240


def test_explicit_rest_and_saved_rest_with_identical_interval_are_deduplicated() -> None:
    interval = Interval(at(9), at(10))
    rest = PlanSlot("rest", interval, preservation="system")
    result = build_schedule(context(elapsed=644, fixed_slots=(rest,)), rest_intervals=(interval,))
    assert [slot for slot in result.slots if slot.kind == "rest"] == [rest]


def test_already_taken_rest_counts_for_the_whole_day_without_adding_fake_past_rest() -> None:
    rest = PlanSlot("rest", Interval(at(8), at(9)), preservation="system")
    ctx = context(elapsed=644, fixed_slots=(rest,), now=at(17, 50))
    result = build_schedule(ctx)
    assert [slot for slot in result.slots if slot.kind == "rest"] == [rest]
    assert not any(w.code == "CRITICAL_REST_UNAVAILABLE" for w in result.warnings)


def test_rests_are_selected_jointly_in_the_only_remaining_hour() -> None:
    ctx = context(elapsed=644)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert [(slot.interval.start, slot.interval.end) for slot in result.slots] == [
        (at(8), at(8, 30)),
        (at(8, 30), at(9)),
    ]
    assert result.metrics.capacity_min == 0
    assert not any(w.code == "CRITICAL_REST_UNAVAILABLE" for w in result.warnings)


@pytest.mark.parametrize("now", [time(8), time(8, 20), time(20)])
def test_rest_shortfall_is_explicit_and_never_replaced_by_new_work(now: time) -> None:
    item = task(duration=5, kind="routine")
    ctx = context(item, elapsed=644, now=datetime.combine(DAY, now, UTC))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(8, 45), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert result.unscheduled[0].reason_codes == ("CRITICAL_REST_UNAVAILABLE",)
    assert any(
        w.code == "CRITICAL_REST_UNAVAILABLE" and w.level == "critical" for w in result.warnings
    )
    assert all(slot.kind != "task" for slot in result.slots)
    assert all(slot.interval.start >= ctx.now for slot in result.slots)


def test_rest_shortfall_preserves_pinned_work_and_its_historical_metadata() -> None:
    pinned = task(duration=60, kind="routine", is_pinned=True, pinned_start=at(8))
    saved = PlanSlot(
        "task", Interval(at(8), at(9)), pinned.ref, True, "pinned", explanation="Не менять"
    )
    ctx = context(pinned, task(1, 5, "routine"), elapsed=644, fixed_slots=(saved,))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert result.slots == (saved,)
    assert result.metrics.planned_min == 60
    assert result.unscheduled[0].task == ctx.tasks[1].ref


def test_critical_rest_can_fulfill_a_required_intellectual_break() -> None:
    first = task(is_pinned=True, pinned_start=at(8))
    second = task(1, is_pinned=True, pinned_start=at(9, 30))
    interval = Interval(at(9), at(9, 30))
    result = build_schedule(context(first, second, elapsed=322), rest_intervals=(interval,))
    assert not any(slot.kind == "break" for slot in result.slots)
    assert sum(slot.kind == "rest" for slot in result.slots) == 1


def test_noon_and_crossing_dates_are_local_not_utc() -> None:
    ctx = context(elapsed=14)
    profile = replace(ctx.profile, birth_utc=at(23), timezone="Asia/Yekaterinburg")
    # Birth crossing is November 15 locally, outside the requested November 14.
    policy = day_policy(profile, DAY)
    assert policy.critical.level == 0
    assert policy.value(Cycle.PHYSICAL) < 0


def test_missing_local_date_has_a_domain_error_instead_of_a_guessed_noon() -> None:
    profile = replace(context().profile, timezone="Pacific/Apia")
    with pytest.raises(PlannerTimeError, match="noon"):
        day_policy(profile, date(2011, 12, 30))


@pytest.mark.parametrize("zone", ["UTC", "Etc/GMT+12"])
def test_calendar_overflow_remains_a_field_aware_domain_error(zone: str) -> None:
    profile = replace(context().profile, timezone=zone)
    with pytest.raises(PlannerTimeError) as caught:
        day_policy(profile, date.max)
    assert caught.value.code == "DATE_RANGE_UNSUPPORTED" and caught.value.field == "day"


def test_dst_day_rest_capacity_uses_elapsed_minutes_not_local_clock_subtraction() -> None:
    day = date(2026, 10, 25)
    ctx = context(elapsed=644)
    profile = replace(
        ctx.profile,
        birth_utc=at(12, day=day) - timedelta(days=644),
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_duration_min=0,
    )
    ctx = replace(ctx, profile=profile, day=day, now=at(0, day=day) - timedelta(days=1))
    result = build_schedule(ctx)
    assert result.metrics.critical_level == 3
    assert result.metrics.capacity_min == (300 - 60) // 2
    assert sum(slot.kind == "rest" for slot in result.slots) == 2


def test_explanation_disambiguates_both_sides_of_a_repeated_clock() -> None:
    day = date(2026, 10, 25)
    item = task(
        duration=60,
        kind="routine",
        planned_date=day,
        is_pinned=True,
        pinned_start=at(0, 30, day=day),
    )
    ctx = context()
    profile = replace(
        ctx.profile,
        timezone="Europe/Berlin",
        work_start=time.min,
        work_end=time(4),
        lunch_duration_min=0,
    )
    ctx = replace(
        ctx, profile=profile, day=day, now=at(0, day=day) - timedelta(days=1), tasks=(item,)
    )
    slot = next(slot for slot in build_schedule(ctx).slots if slot.task == item.ref)
    assert slot.explanation and "02:30 +0200–02:30 +0100" in slot.explanation


def test_future_snapshots_are_immutable_copies_of_the_input_collections() -> None:
    items = [replace(task(), planned_date=DAY + timedelta(days=1))]
    snapshot = FutureDay(DAY + timedelta(days=1), items)  # type: ignore[arg-type]
    items.clear()
    assert len(snapshot.tasks) == 1
    dates = [snapshot]
    ctx = context(future_days=dates)
    dates.clear()
    assert ctx.future_days == (snapshot,)


@pytest.mark.parametrize("offset", [-1, 0, 8])
def test_future_dates_must_be_within_the_next_seven_days(offset: int) -> None:
    with pytest.raises(ValueError, match="seven"):
        context(future_days=(future(offset),))


def test_same_day_or_task_cannot_be_represented_twice_in_future_context() -> None:
    with pytest.raises(ValueError, match="unique"):
        context(future_days=(future(), future()))
    with pytest.raises(ValueError, match="multiple days"):
        context(task(), future_days=(future(1, task()),))
    with pytest.raises(ValueError, match="multiple days"):
        context(future_days=(future(1, task()), future(2, task())))


def test_future_tasks_require_correct_dates_and_persisted_unique_ids() -> None:
    day = DAY + timedelta(days=1)
    with pytest.raises(ValueError, match="belong"):
        FutureDay(day, (task(),))
    item = replace(task(), planned_date=day)
    with pytest.raises(ValueError, match="unique"):
        FutureDay(day, (item, item))
    with pytest.raises(ValueError, match="persisted"):
        FutureDay(day, (replace(item, ref=TaskRef(task_index=0)),))


@pytest.mark.parametrize("problem", ["missing_preservation", "unknown_task", "duplicate"])
def test_future_reservations_require_known_unique_preserved_tasks(problem: str) -> None:
    day = DAY + timedelta(days=1)
    item = replace(task(), planned_date=day)
    slot = PlanSlot("task", Interval(at(8, day=day), at(9, day=day)), item.ref, preservation="past")
    slots = (slot,)
    if problem == "missing_preservation":
        slots = (replace(slot, preservation=None),)
    elif problem == "unknown_task":
        slots = (replace(slot, task=TaskRef(task_id=UUID(int=999))),)
    else:
        slots = (slot, slot)
    with pytest.raises(ValueError, match="reservations"):
        FutureDay(day, (item,), slots)


def test_eligible_work_moves_to_nearest_confirmed_noncritical_positive_day() -> None:
    item = task()
    ctx = context(item, elapsed=14, future_days=(future(2), future(1)))
    result = build_schedule(ctx)
    assert len(result.moves) == 1
    move = result.moves[0]
    assert (move.task, move.from_date, move.to_date, move.reason_code) == (
        item.ref,
        DAY,
        DAY + timedelta(days=1),
        "MOVED_FROM_CRITICAL_DAY",
    )
    assert not result.unscheduled and result.metrics.planned_min == 0
    assert result.metrics.requested_min == result.metrics.moved_min == 60
    target = result.future_plans[0]
    assert target.day == move.to_date
    assert any(
        slot.task == item.ref and "MOVED_FROM_CRITICAL_DAY" in slot.reason_codes
        for slot in target.slots
    )
    assert target.metrics.planned_min == 60 and not target.unscheduled
    assert not target.future_plans
    assert len(result.status_changes) == 1 and result.status_changes[0].next == "scheduled"
    assert not target.status_changes
    assert item.planned_date == DAY and item.status == "pending"
    assert ctx.future_days[0].tasks == ctx.future_days[1].tasks == ()
    assert not any(w.code == "OVERLOAD" for w in result.warnings)
    warning = next(w for w in result.warnings if w.code == "MOVED_FROM_CRITICAL_DAY")
    assert warning.target_date == target.day
    assert f"{target.metrics.planned_min} из {target.metrics.capacity_min}" in warning.message


def test_a_scheduled_task_moved_to_another_day_is_never_marked_pending() -> None:
    result = build_schedule(context(task(status="scheduled"), elapsed=14, future_days=(future(),)))
    assert result.moves and not result.status_changes and not result.future_plans[0].status_changes


@pytest.mark.parametrize(
    "item",
    [
        task(duration=59),
        task(kind="creative", priority="high"),
        task(kind="routine", priority="high"),
    ],
)
def test_short_nonpriority_work_and_other_types_do_not_move_automatically(item: PlanTask) -> None:
    result = build_schedule(context(item, elapsed=14, future_days=(future(),)))
    assert not result.moves and not result.future_plans
    assert any(slot.task == item.ref for slot in result.slots)


def test_short_high_priority_work_is_eligible_for_automatic_transfer() -> None:
    result = build_schedule(
        context(task(duration=5, priority="high"), elapsed=14, future_days=(future(),))
    )
    assert len(result.moves) == 1 and result.metrics.moved_min == 5


def test_missing_future_snapshot_is_not_assumed_to_be_an_empty_day() -> None:
    result = build_schedule(context(task(), elapsed=14, future_days=(future(2),)))
    assert result.moves[0].to_date == DAY + timedelta(days=2)
    unavailable = build_schedule(context(task(), elapsed=14))
    assert not unavailable.moves
    assert any(w.code == "CRITICAL_MOVE_UNAVAILABLE" for w in unavailable.warnings)
    assert unavailable.metrics.planned_min == 60


@pytest.mark.parametrize("offset", [0, 1])
def test_deadline_is_an_inclusive_calendar_day_when_selecting_target(offset: int) -> None:
    item = task(deadline=DAY + timedelta(days=offset))
    result = build_schedule(context(item, elapsed=14, future_days=(future(),)))
    assert bool(result.moves) == bool(offset)
    assert item.deadline == DAY + timedelta(days=offset)


def test_auto_transfer_skips_nonworking_target_dates_but_not_the_explicit_source_day() -> None:
    ctx = context(task(), elapsed=14, future_days=(future(1), future(2)))
    ctx = replace(ctx, profile=replace(ctx.profile, work_days=(1,)))
    result = build_schedule(ctx)
    assert result.moves[0].to_date.isoweekday() == 1
    assert result.moves[0].to_date == DAY + timedelta(days=2)


def test_negative_relevant_cycle_and_a_critical_target_are_rejected() -> None:
    negative = build_schedule(
        context(
            task(kind="physical"), elapsed=14, future_days=tuple(future(i) for i in range(1, 8))
        )
    )
    assert not negative.moves
    critical = build_schedule(context(task(kind="physical"), elapsed=28, future_days=(future(5),)))
    assert not critical.moves


@pytest.mark.parametrize("mode", ["preview", "initial"])
def test_preview_and_initial_plans_never_hide_incomplete_work_by_moving_it(mode: str) -> None:
    item = task(duration=480)
    if mode == "preview":
        item = replace(item, ref=TaskRef(task_index=0))
    ctx = context(item, elapsed=14, mode=mode, future_days=(future(),))
    result = build_schedule(ctx)
    assert not result.moves and not result.future_plans
    assert result.unscheduled[0].task == item.ref and result.metrics.moved_min == 0


def test_pinned_and_saved_unpinned_work_cannot_be_automatically_transferred() -> None:
    pinned = task(is_pinned=True, pinned_start=at(8))
    started = task(1, status="scheduled")
    saved = PlanSlot("task", Interval(at(10), at(11)), started.ref, preservation="started")
    ctx = context(
        pinned, started, elapsed=14, now=at(10, 30), fixed_slots=(saved,), future_days=(future(),)
    )
    result = build_schedule(ctx)
    assert not result.moves and saved in result.slots
    assert {slot.task for slot in result.slots if slot.task is not None} == {
        pinned.ref,
        started.ref,
    }


def test_done_and_skipped_tasks_never_become_transfer_candidates() -> None:
    done, skipped = task(status="done"), task(1, status="skipped")
    saved = PlanSlot("task", Interval(at(8), at(9)), done.ref, preservation="done")
    result = build_schedule(
        context(done, skipped, elapsed=14, fixed_slots=(saved,), future_days=(future(),))
    )
    assert not result.moves and not result.status_changes
    assert saved in result.slots


def test_total_free_minutes_are_not_enough_without_a_contiguous_target_interval() -> None:
    day = DAY + timedelta(days=1)
    residents = tuple(
        task(index + 10, 15, "routine", is_pinned=True, pinned_start=at(hour, 45, day=day))
        for index, hour in enumerate(range(8, 12))
    )
    ctx = context(task(), elapsed=14, future_days=(future(1, *residents),))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(12), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert not result.moves and not result.future_plans
    assert result.metrics.planned_min == 60


def test_high_priority_incoming_work_must_not_displace_an_existing_lower_priority_task() -> None:
    resident = task(10, 100, priority="low")
    incoming = task(priority="high")
    ctx = context(incoming, elapsed=14, future_days=(future(1, resident),))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert not result.moves and not result.future_plans
    assert ctx.future_days[0].tasks[0].status == "pending"


def test_multiple_incoming_tasks_share_a_capacity_checked_target_snapshot() -> None:
    first, second = task(), task(1)
    ctx = context(first, second, elapsed=14, future_days=(future(),))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert [move.task for move in result.moves] == [first.ref]
    assert len(result.future_plans) == 1
    target = result.future_plans[0]
    assert target.metrics.planned_min == 60 <= target.metrics.capacity_min
    assert {slot.task for slot in target.slots if slot.task is not None} == {first.ref}
    assert {slot.task for slot in result.slots if slot.task is not None} == {second.ref}
    assert len({change.task for change in (*result.status_changes, *target.status_changes)}) == 2


def test_resident_status_changes_are_retained_in_the_returned_target_plan() -> None:
    resident = task(10, 5, "routine")
    result = build_schedule(context(task(), elapsed=14, future_days=(future(1, resident),)))
    assert [change.task for change in result.future_plans[0].status_changes] == [resident.ref]
    assert [change.task for change in result.status_changes] == [task().ref]


def test_later_incoming_work_cannot_overwrite_an_earlier_accepted_move_or_its_status() -> None:
    first, second = task(), task(1)
    result = build_schedule(context(first, second, elapsed=14, future_days=(future(),)))
    assert len(result.moves) == 2 and len(result.future_plans) == 1
    target = result.future_plans[0]
    assert {slot.task for slot in target.slots if slot.task is not None} == {first.ref, second.ref}
    assert target.metrics.planned_min == result.metrics.moved_min == 120
    assert not target.unscheduled and not result.unscheduled
    assert {change.task for change in result.status_changes} == {first.ref, second.ref}
    assert not target.status_changes
    assert all(
        "120 из" in w.message for w in result.warnings if w.code == "MOVED_FROM_CRITICAL_DAY"
    )


def test_target_saved_slots_keep_their_metadata_when_incoming_work_is_added() -> None:
    day = DAY + timedelta(days=1)
    resident = task(10, 30, "routine", is_pinned=True, pinned_start=at(8, day=day))
    saved = PlanSlot(
        "task",
        Interval(at(8, day=day), at(8, 30, day=day)),
        resident.ref,
        is_pinned=True,
        preservation="pinned",
        score=0.75,
        reason_codes=("SAVED",),
        explanation="Не менять",
    )
    ctx = context(task(), elapsed=14, future_days=(future(1, resident, fixed=(saved,)),))
    result = build_schedule(ctx)
    assert result.moves and saved in result.future_plans[0].slots


def test_an_unavailable_nearby_target_does_not_hide_a_later_valid_day() -> None:
    resident = task(10, 100, priority="low")
    ctx = context(task(priority="high"), elapsed=14, future_days=(future(1, resident), future(2)))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert result.moves[0].to_date == DAY + timedelta(days=2)
    assert [plan.day for plan in result.future_plans] == [DAY + timedelta(days=2)]


def test_overflow_advice_is_capacity_checked_and_does_not_apply_a_move() -> None:
    item = task(kind="routine")
    ctx = context(item, now=at(20), future_days=(future(),))
    result = build_schedule(ctx)
    suggestion = next(w for w in result.warnings if w.code == "SUGGESTED_MOVE")
    assert suggestion.task == item.ref and suggestion.target_date == DAY + timedelta(days=1)
    assert "60 мин помещается целиком" in suggestion.message
    assert result.unscheduled[0].task == item.ref
    assert result.moves == result.future_plans == ()
    assert result.metrics.moved_min == 0 and item.planned_date == DAY


def test_advice_prefers_a_confirmed_peak_day_within_the_search_window() -> None:
    item = task(duration=30, kind="physical")
    result = build_schedule(
        context(item, elapsed=644, now=at(20), future_days=(future(1), future(2)))
    )
    suggestion = next(w for w in result.warnings if w.code == "SUGGESTED_MOVE")
    assert suggestion.target_date == DAY + timedelta(days=2)
    assert not result.moves


def test_advisory_moves_do_not_collectively_overbook_the_same_future_day() -> None:
    ctx = context(
        task(kind="routine"), task(1, kind="routine"), now=at(20), future_days=(future(),)
    )
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert sum(w.code == "SUGGESTED_MOVE" for w in result.warnings) == 1
    assert not result.moves and not result.future_plans


@pytest.mark.parametrize(("minutes", "overload"), [(85, False), (86, True)])
def test_overload_threshold_is_strictly_greater_than_85_percent(
    minutes: int, overload: bool
) -> None:
    item = task(duration=minutes, kind="routine", is_pinned=True, pinned_start=at(8))
    ctx = context(item)
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(9, 40), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert any(w.code == "OVERLOAD" for w in result.warnings) == overload
    assert result.metrics.capacity_min == 100


def test_overloaded_day_can_suggest_moving_a_placed_low_priority_task() -> None:
    item = task(duration=110, kind="routine", priority="low")
    ctx = context(item, future_days=(future(),))
    ctx = replace(ctx, profile=replace(ctx.profile, work_end=time(10), lunch_duration_min=0))
    result = build_schedule(ctx)
    assert not result.unscheduled and any(slot.task == item.ref for slot in result.slots)
    assert any(w.code == "SUGGESTED_MOVE" and w.task == item.ref for w in result.warnings)
    assert not result.moves and not result.future_plans


def test_explanations_use_actual_interval_cycle_mean_and_preferred_start_bonus() -> None:
    from app.modules.biorhythm.engine import percent
    from app.modules.planner.energy import score_interval

    item = task(duration=30, preferred_start=time(10))
    ctx = context(item)
    slot = next(slot for slot in build_schedule(ctx).slots if slot.task == item.ref)
    rating = score_interval(ctx.profile, item, slot.interval)
    assert rating.cycle_mean is not None
    assert slot.explanation and f"{percent(rating.cycle_mean):g}%" in slot.explanation
    assert "PREFERRED_TIME" in slot.reason_codes and "CIRCADIAN_WINDOW" in slot.reason_codes
    assert ("INTELLECTUAL_PEAK" in slot.reason_codes) == (rating.cycle_mean >= 0.5)


def test_negative_biorhythm_is_never_described_as_a_peak() -> None:
    item = task(duration=30, kind="physical")
    result = build_schedule(context(item, elapsed=14))
    slot = next(slot for slot in result.slots if slot.task == item.ref)
    assert "PHYSICAL_PEAK" not in slot.reason_codes
    assert slot.explanation and "-" in slot.explanation
    assert any(w.code == "CYCLE_MINIMUM" and "12:00" in w.message for w in result.warnings)


def test_new_pins_routine_lunch_and_rest_get_truthful_explanations() -> None:
    pinned = task(duration=5, kind="routine", is_pinned=True, pinned_start=at(8))
    routine = task(1, 5, "routine")
    result = build_schedule(context(pinned, routine, elapsed=644))
    pin = next(slot for slot in result.slots if slot.task == pinned.ref)
    work = next(slot for slot in result.slots if slot.task == routine.ref)
    assert "PINNED_BY_USER" in pin.reason_codes
    assert "LOW_ENERGY_ROUTINE" in work.reason_codes
    assert all(
        "CRITICAL_DAY_REST" in slot.reason_codes for slot in result.slots if slot.kind == "rest"
    )
    assert any("LUNCH" in slot.reason_codes for slot in result.slots)


@pytest.mark.parametrize(
    ("first_kind", "duration", "reason"),
    [
        ("intellectual", 60, "BETWEEN_INTELLECTUAL_TASKS"),
        ("routine", 100, "BREAK_AFTER_LONG_WORK"),
        ("physical", 30, "BETWEEN_INTENSIVE_TASKS"),
    ],
)
def test_break_explanations_reflect_the_constraint_that_created_them(
    first_kind: TaskKind, duration: int, reason: str
) -> None:
    first = task(duration=duration, kind=first_kind, is_pinned=True, pinned_start=at(8))
    second = task(1, 5, "intellectual", is_pinned=True, pinned_start=at(10, 30))
    result = build_schedule(context(first, second))
    rest = next(slot for slot in result.slots if slot.kind == "break")
    assert reason in rest.reason_codes and rest.explanation


def test_four_consecutive_intellectual_tasks_generate_an_alternation_recommendation() -> None:
    items = tuple(task(i, 5, is_pinned=True, pinned_start=at(8 + i)) for i in range(4))
    result = build_schedule(context(*items))
    assert sum(w.code == "ALTERNATING_TYPES" for w in result.warnings) == 1
    mixed = (*items[:2], replace(items[2], kind="routine"), items[3])
    assert not any(w.code == "ALTERNATING_TYPES" for w in build_schedule(context(*mixed)).warnings)


def test_policy_result_is_deterministic_under_source_and_future_input_permutations() -> None:
    ctx = context(task(), task(1, 20, "routine"), elapsed=14, future_days=(future(1), future(2)))
    assert build_schedule(ctx) == build_schedule(
        replace(ctx, tasks=ctx.tasks[::-1], future_days=ctx.future_days[::-1])
    )
