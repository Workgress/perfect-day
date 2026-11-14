from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, get_args
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Date, DateTime

from app.modules.planner.contracts import (
    Chronotype,
    Interval,
    PlanContext,
    PlanMode,
    PlanProfile,
    PlanSlot,
    PlanTask,
    Priority,
    SlotKind,
    TaskKind,
    TaskRef,
    TaskState,
    TaskStatusChange,
)
from app.modules.schedule.models import SlotKind as StoredSlotKind
from app.modules.tasks.models import Task, TaskPriority, TaskStatus, TaskType
from app.modules.users.models import Chronotype as StoredChronotype

DAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 9, tzinfo=UTC)
TASK_ID = UUID("11111111-1111-4111-8111-111111111111")


def profile() -> PlanProfile:
    return PlanProfile(
        birth_utc=datetime(2000, 1, 1, 12, tzinfo=UTC),
        timezone="UTC",
        chronotype="dove",
        work_start=time(8),
        work_end=time(18),
        sleep_time=time(23),
    )


def task(ref: TaskRef | None = None) -> PlanTask:
    return PlanTask(
        ref=ref or TaskRef(task_index=0),
        kind="intellectual",
        duration_min=17,
        planned_date=DAY,
    )


def context(tasks: tuple[PlanTask, ...], mode: PlanMode = "preview") -> PlanContext:
    return PlanContext(profile(), DAY, NOW, tasks, mode)


def test_contract_literals_match_existing_database_enums() -> None:
    for alias, stored in (
        (TaskKind, TaskType),
        (Priority, TaskPriority),
        (TaskState, TaskStatus),
        (SlotKind, StoredSlotKind),
        (Chronotype, StoredChronotype),
    ):
        assert set(get_args(alias.__value__)) == {value.value for value in stored}
    assert isinstance(Task.__table__.c.deadline.type, Date)
    assert not isinstance(Task.__table__.c.deadline.type, DateTime)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"task_id": TASK_ID, "task_index": 0},
        {"task_index": -1},
        {"task_index": True},
        {"task_index": 1.5},
        {"task_id": str(TASK_ID)},
    ],
)
def test_draft_and_persisted_references_cannot_be_confused(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TaskRef(**fields)


@pytest.mark.parametrize("duration", [5, 17, 480])
def test_valid_duration_is_preserved_without_grid_rounding(duration: int) -> None:
    planned = replace(task(), duration_min=duration)
    assert planned.duration_min == duration


@pytest.mark.parametrize("duration", [4, 481, True, "17", 17.5])
def test_invalid_duration_is_not_coerced(duration: Any) -> None:
    with pytest.raises(ValueError, match="duration_min"):
        replace(task(), duration_min=duration)


def test_date_deadline_is_preserved_and_datetime_is_not_silently_truncated() -> None:
    assert replace(task(), deadline=DAY).deadline == DAY
    with pytest.raises(ValueError, match="deadline"):
        replace(task(), deadline=NOW)
    with pytest.raises(ValueError, match="planned_date"):
        replace(task(), planned_date=NOW)


def test_utc_interval_preserves_repeated_hour_instead_of_comparing_wall_clock() -> None:
    tz = ZoneInfo("Europe/Berlin")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=0)
    second = datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=1)
    interval = Interval(first, second)
    assert interval.end - interval.start == timedelta(hours=1)
    assert interval.start.tzinfo is interval.end.tzinfo is UTC


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (NOW, NOW),
        (NOW, NOW - timedelta(minutes=1)),
        (NOW.replace(tzinfo=None), NOW + timedelta(minutes=1)),
        (NOW, (NOW + timedelta(minutes=1)).replace(tzinfo=None)),
    ],
)
def test_invalid_or_naive_interval_is_rejected(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError):
        Interval(start, end)


def test_changing_current_timezone_does_not_shift_computational_birth() -> None:
    original = profile()
    changed = replace(original, timezone="Asia/Yekaterinburg")
    assert changed.birth_utc == original.birth_utc
    assert changed.work_start == original.work_start


@pytest.mark.parametrize(
    "fields",
    [
        {"work_start": time(20)},
        {"work_start": time(8, tzinfo=UTC)},
        {"sleep_time": time(23, 0, 1)},
        {"timezone": "Missing/Zone"},
        {"lunch_duration_min": True},
        {"work_days": (1, 1)},
        {"work_days": (True,)},
    ],
)
def test_profile_rejects_incompatible_calculation_inputs(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(profile(), **fields)


def test_early_work_and_sleep_after_midnight_do_not_use_hidden_wake_default() -> None:
    early = replace(profile(), work_start=time(5), sleep_time=time(1))
    assert early.work_start == time(5)
    # Saturday onboarding is a valid calculation request despite default Mon–Fri.
    planned = PlanContext(early, DAY, NOW, (task(),), "preview")
    assert planned.day.isoweekday() == 6


@pytest.mark.parametrize(
    ("mode", "ref"),
    [("preview", TaskRef(task_id=TASK_ID)), ("replan", TaskRef(task_index=0))],
)
def test_context_requires_identity_of_the_selected_mode(mode: PlanMode, ref: TaskRef) -> None:
    with pytest.raises(ValueError):
        context((task(ref),), mode)


def test_preview_retains_original_indexes_even_when_input_order_changes() -> None:
    second = task(TaskRef(task_index=1))
    first = task(TaskRef(task_index=0))
    planned = context((second, first))
    assert planned.tasks == (second, first)
    assert context((task(TaskRef(task_id=TASK_ID)),), "replan").tasks[0].ref.task_id == TASK_ID


def test_context_rejects_lost_indexes_duplicate_tasks_and_another_date() -> None:
    with pytest.raises(ValueError, match="without gaps"):
        context((task(TaskRef(task_index=1)),))
    with pytest.raises(ValueError, match="unique"):
        context((task(), task()))
    with pytest.raises(ValueError, match="planned day"):
        context((replace(task(), planned_date=DAY + timedelta(days=1)),))


def test_equivalent_offsets_produce_identical_contexts() -> None:
    original = context((task(),))
    with_offset = NOW.astimezone(ZoneInfo("Asia/Yekaterinburg"))
    assert replace(original, now=with_offset) == original


def test_pinned_start_needs_offset_and_is_preserved_exactly() -> None:
    with pytest.raises(ValueError, match="pinned_start"):
        replace(task(), is_pinned=True)
    with pytest.raises(ValueError):
        replace(task(), is_pinned=True, pinned_start=NOW.replace(tzinfo=None))
    at = (NOW + timedelta(minutes=7)).astimezone(ZoneInfo("Asia/Yekaterinburg"))
    assert replace(task(), is_pinned=True, pinned_start=at).pinned_start == NOW + timedelta(
        minutes=7
    )


def test_fixed_slots_keep_reference_to_existing_input_and_preservation_reason() -> None:
    persisted = task(TaskRef(task_id=TASK_ID))
    fixed = PlanSlot(
        "task",
        Interval(NOW, NOW + timedelta(minutes=17)),
        task=persisted.ref,
        is_pinned=True,
        preservation="pinned",
    )
    planned = replace(context((persisted,), "replan"), fixed_slots=(fixed,))
    assert planned.fixed_slots == (fixed,)
    with pytest.raises(ValueError, match="input task"):
        replace(context((), "replan"), fixed_slots=(fixed,))
    with pytest.raises(ValueError, match="preservation"):
        replace(planned, fixed_slots=(replace(fixed, preservation=None),))
    with pytest.raises(ValueError, match="multiple fixed"):
        replace(planned, fixed_slots=(fixed, fixed))


def test_system_slot_cannot_reference_a_task_or_be_a_pinned_task() -> None:
    interval = Interval(NOW, NOW + timedelta(minutes=15))
    for fields in ({"task": task().ref}, {"is_pinned": True}):
        with pytest.raises(ValueError):
            PlanSlot("break", interval, **fields)
    with pytest.raises(ValueError):
        PlanSlot("task", interval)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_scores_are_rejected_without_rejecting_preference_bonus(score: float) -> None:
    slot = PlanSlot("task", Interval(NOW, NOW + timedelta(minutes=17)), task=task().ref, score=1.3)
    assert slot.score == 1.3
    with pytest.raises(ValueError, match="finite"):
        replace(slot, score=score)


@pytest.mark.parametrize(
    ("previous", "next_state"), [("done", "scheduled"), ("scheduled", "skipped")]
)
def test_planner_cannot_emit_user_completion_or_skip_changes(
    previous: Any, next_state: Any
) -> None:
    with pytest.raises(ValueError, match="never done/skipped"):
        TaskStatusChange(task().ref, previous, next_state)


def test_scheduling_delta_only_contains_an_actual_pending_scheduled_transition() -> None:
    delta = TaskStatusChange(task().ref, "pending", "scheduled")
    assert delta.next == "scheduled"
    with pytest.raises(ValueError, match="actually change"):
        TaskStatusChange(task().ref, "pending", "pending")
