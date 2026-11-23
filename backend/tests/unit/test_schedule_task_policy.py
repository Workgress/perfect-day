from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.task_policy import TaskReplanScope, task_replan_scope
from app.modules.tasks.events import TaskChanged, TaskOperation

DAY = date(2026, 11, 17)
NEXT_DAY = date(2026, 11, 18)


def event(operation: TaskOperation = "updated", *fields: str) -> TaskChanged:
    return TaskChanged(
        user_id=UUID(int=1),
        task_id=UUID(int=2),
        operation=operation,
        changed_fields=frozenset(fields),
        old_planned_date=DAY,
        new_planned_date=DAY,
        version=2,
        occurred_at=datetime(2026, 11, 17, 23, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "field",
    [
        "planned_date",
        "duration_min",
        "type",
        "priority",
        "deadline",
        "preferred_start",
        "is_pinned",
        "pinned_start",
        "is_date_locked",
        "actual_start",
        "status",
        "deleted_at",
    ],
)
def test_placement_change_replans_the_task_day(field: str) -> None:
    assert task_replan_scope(event("updated", field)) == TaskReplanScope(
        (DAY,), ScheduleTrigger.TASK_UPDATED
    )


@pytest.mark.parametrize(
    "fields", [(), ("title",), ("description",), ("title", "description", "updated_at", "version")]
)
def test_nonplacement_patch_does_not_replan(fields: tuple[str, ...]) -> None:
    assert task_replan_scope(event("updated", *fields)) is None


@pytest.mark.parametrize(
    ("operation", "old", "new", "trigger", "expected"),
    [
        ("created", None, DAY, ScheduleTrigger.TASK_CREATED, (DAY,)),
        ("deleted", DAY, None, ScheduleTrigger.TASK_DELETED, (DAY,)),
        ("updated", DAY, NEXT_DAY, ScheduleTrigger.TASK_UPDATED, (DAY, NEXT_DAY)),
        ("updated", NEXT_DAY, DAY, ScheduleTrigger.TASK_UPDATED, (DAY, NEXT_DAY)),
        ("completed", DAY, DAY, ScheduleTrigger.STATUS_CHANGED, (DAY,)),
        ("skipped", DAY, DAY, ScheduleTrigger.STATUS_CHANGED, (DAY,)),
        ("reopened", DAY, DAY, ScheduleTrigger.STATUS_CHANGED, (DAY,)),
    ],
)
def test_operations_select_dates_and_schedule_trigger(
    operation: TaskOperation,
    old: date | None,
    new: date | None,
    trigger: ScheduleTrigger,
    expected: tuple[date, ...],
) -> None:
    change = replace(event(operation, "planned_date"), old_planned_date=old, new_planned_date=new)
    assert task_replan_scope(change) == TaskReplanScope(expected, trigger)


def test_mixed_content_and_placement_patch_still_replans() -> None:
    assert task_replan_scope(event("updated", "title", "description", "duration_min")) == (
        TaskReplanScope((DAY,), ScheduleTrigger.TASK_UPDATED)
    )


def test_event_timestamp_does_not_replace_the_task_calendar_dates() -> None:
    change = replace(
        event("updated", "priority"), old_planned_date=date.min, new_planned_date=date.max
    )
    assert task_replan_scope(change) == TaskReplanScope(
        (date.min, date.max), ScheduleTrigger.TASK_UPDATED
    )


@pytest.mark.parametrize("operation", ["created", "updated", "deleted", "completed"])
def test_no_dates_produces_no_schedule_request(operation: TaskOperation) -> None:
    change = replace(event(operation, "status"), old_planned_date=None, new_planned_date=None)
    assert task_replan_scope(change) is None
