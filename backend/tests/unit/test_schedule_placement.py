from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.planner.contracts import Interval
from app.modules.schedule.placement import check_selected_placement
from tests.unit.test_planner_replan import at, context, slot, task


def test_movable_task_does_not_collide_with_its_old_interval() -> None:
    item = task()
    old = slot(item, 14)
    ctx = context(item, now=at(7))
    assert check_selected_placement(ctx, item, old.interval, (old,)) == ()
    assert check_selected_placement(ctx, item, Interval(at(9), at(9, 30)), (old,)) == ()
    assert ctx.fixed_slots == () and old.preservation is None


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [(7, 7.5, "PAST_START"), (18, 18.5, "OUTSIDE_WORK_WINDOW"), (12, 12.5, "INTERVAL_OCCUPIED")],
)
def test_interval_refusals_explain_current_time_work_window_and_lunch(
    start: float, end: float, code: str
) -> None:
    item = task()
    interval = Interval(at(int(start), int(start % 1 * 60)), at(int(end), int(end % 1 * 60)))
    result = check_selected_placement(context(item, now=at(8)), item, interval, ())
    refusal = next(reason for reason in result if reason.code == code)
    assert refusal.message
    if code == "INTERVAL_OCCUPIED":
        assert "обедом" in refusal.message and "12:00" in refusal.message
        assert refusal.conflicting_task_id is None


def test_occupied_interval_identifies_conflicting_task_and_real_times() -> None:
    item, resident = task(), task(1)
    result = check_selected_placement(
        context(item, resident, now=at(7)),
        item,
        Interval(at(10), at(10, 30)),
        (slot(resident, 10),),
    )
    refusal = next(reason for reason in result if reason.code == "INTERVAL_OCCUPIED")
    assert refusal.conflicting_task_id == resident.ref.task_id
    assert "10:00" in refusal.message and "10:30" in refusal.message


@pytest.mark.parametrize("protection", ["pinned", "started", "past"])
def test_protected_task_accepts_its_saved_interval_and_refuses_a_move(protection: str) -> None:
    item = task(
        is_pinned=protection == "pinned",
        pinned_start=at(14) if protection == "pinned" else None,
        actual_start=at(9) if protection == "started" else None,
    )
    old = slot(item, 8 if protection == "past" else 14)
    ctx = context(item)
    assert check_selected_placement(ctx, item, old.interval, (old,)) == ()
    result = check_selected_placement(ctx, item, Interval(at(11), at(11, 30)), (old,))
    expected = {"pinned": "TASK_PINNED", "started": "TASK_STARTED", "past": "TASK_ALREADY_RESERVED"}
    assert [reason.code for reason in result] == [expected[protection]]


def test_new_pin_is_checked_for_collisions_instead_of_automatically_accepted() -> None:
    item = task(is_pinned=True, pinned_start=at(12))
    result = check_selected_placement(
        context(item, now=at(7)), item, Interval(at(12), at(12, 30)), ()
    )
    assert any(reason.code == "INTERVAL_OCCUPIED" for reason in result)


def test_deadline_and_duration_are_checked() -> None:
    item = task(deadline=at(9))
    ctx = context(item, now=at(7))
    result = check_selected_placement(ctx, item, Interval(at(9), at(9, 30)), ())
    assert any(reason.code == "DEADLINE_EXCEEDED" for reason in result)
    result = check_selected_placement(ctx, item, Interval(at(8), at(9)), ())
    assert [reason.code for reason in result] == ["DURATION_MISMATCH"]


def test_required_break_between_intellectual_tasks_is_checked() -> None:
    resident, item = task(kind="intellectual"), task(1, kind="intellectual")
    ctx = context(resident, item, now=at(7))
    result = check_selected_placement(ctx, item, Interval(at(9, 30), at(10)), (slot(resident, 9),))
    assert [reason.code for reason in result] == ["INSUFFICIENT_BREAK"]


@pytest.mark.parametrize("status", ["done", "skipped"])
def test_inactive_task_cannot_be_placed(status: str) -> None:
    item = task(status=status)
    result = check_selected_placement(
        context(item), item, Interval(at(14), at(14, 30)), (slot(item, 14),)
    )
    assert [reason.code for reason in result] == ["TASK_INACTIVE"]


@pytest.mark.parametrize("kind", ["routine", "intellectual"])
def test_critical_load_and_intensity_limits_are_checked(kind: str) -> None:
    item = task(duration=480 if kind == "routine" else 180, kind=kind)
    ctx = context(item, elapsed=14, now=at(7))
    ctx = replace(ctx, profile=replace(ctx.profile, lunch_duration_min=0))
    result = check_selected_placement(
        ctx, item, Interval(at(8), at(8) + timedelta(minutes=item.duration_min)), ()
    )
    expected = "DAY_CAPACITY_EXCEEDED" if kind == "routine" else "INTENSITY_CAPACITY_EXCEEDED"
    assert any(reason.code == expected for reason in result)


def test_critical_rest_can_be_reserved_around_the_selected_interval() -> None:
    item = task(duration=60)
    ctx = context(item, elapsed=966, now=at(7))
    assert check_selected_placement(ctx, item, Interval(at(10), at(11)), ()) == ()


def test_explicit_reservations_are_checked_without_a_previous_schedule() -> None:
    item, resident = task(), task(1, is_pinned=True, pinned_start=at(10))
    fixed = replace(slot(resident, 10), preservation="pinned")
    ctx = context(item, resident, now=at(7), fixed_slots=(fixed,))
    result = check_selected_placement(ctx, item, Interval(at(10), at(10, 30)), ())
    assert any(reason.conflicting_task_id == resident.ref.task_id for reason in result)
