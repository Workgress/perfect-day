from dataclasses import dataclass
from datetime import date

from app.modules.schedule.models import ScheduleTrigger
from app.modules.tasks.events import TaskChanged

REPLAN_FIELDS = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class TaskReplanScope:
    days: tuple[date, ...]
    trigger: ScheduleTrigger


def task_replan_scope(event: TaskChanged) -> TaskReplanScope | None:
    dates: tuple[date | None, ...]
    if event.operation == "created":
        dates = (event.new_planned_date,)
        trigger = ScheduleTrigger.TASK_CREATED
    elif event.operation == "deleted":
        dates = (event.old_planned_date,)
        trigger = ScheduleTrigger.TASK_DELETED
    else:
        if event.operation == "updated" and not event.changed_fields & REPLAN_FIELDS:
            return None
        dates = (event.old_planned_date, event.new_planned_date)
        trigger = (
            ScheduleTrigger.STATUS_CHANGED
            if event.operation in {"completed", "skipped", "reopened"}
            else ScheduleTrigger.TASK_UPDATED
        )
    days = tuple(sorted({day for day in dates if day is not None}))
    return TaskReplanScope(days, trigger) if days else None
