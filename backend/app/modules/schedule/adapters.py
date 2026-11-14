"""Conversions between existing ORM rows and immutable planner snapshots."""

from dataclasses import asdict, replace
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.core.errors import AppError
from app.modules.planner.contracts import (
    Interval,
    PlanProfile,
    PlanResult,
    PlanSlot,
    PlanTask,
    TaskRef,
    TaskState,
)
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.schedule.models import SlotKind as StoredSlotKind
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.schemas import ProfileState
from app.modules.users.service import ProfileIncompleteError


def profile_snapshot(state: ProfileState | None) -> PlanProfile:
    if state is None or state.birth_at_utc is None or state.chronotype is None:
        raise ProfileIncompleteError()
    try:
        return PlanProfile(
            state.birth_at_utc,
            state.timezone,
            state.chronotype.value,
            state.work_start,
            state.work_end,
            state.sleep_time,
            state.lunch_start,
            state.lunch_duration_min,
            tuple(state.work_days),
        )
    except ValueError as exc:
        raise ProfileIncompleteError() from exc


def task_snapshot(row: Task) -> PlanTask:
    # Soft-deleted noncompleted history stays visible but cannot be scheduled again.
    status = (
        "skipped"
        if row.deleted_at is not None and row.status != TaskStatus.DONE
        else row.status.value
    )
    return PlanTask(
        TaskRef(task_id=row.id),
        row.type.value,
        row.duration_min,
        row.planned_date,
        row.priority.value,
        cast(TaskState, status),
        row.preferred_start,
        row.deadline,
        row.is_pinned,
        row.pinned_start,
        row.created_at,
    )


def saved_slots(schedule: Schedule | None, tasks: dict[UUID, Task]) -> tuple[PlanSlot, ...]:
    if schedule is None:
        return ()
    result = []
    for row in schedule.slots:
        if row.kind.value == "task" and (row.task_id is None or row.task_id not in tasks):
            raise AppError(409, "CONFLICT", "Для сохранения истории не хватает данных задачи")
        result.append(
            PlanSlot(
                row.kind.value,
                Interval(row.start_at, row.end_at),
                TaskRef(task_id=row.task_id) if row.task_id is not None else None,
                row.is_pinned,
                score=float(row.score) if row.score is not None else None,
                reason_codes=tuple(row.reason_codes),
                explanation=row.explanation,
            )
        )
    return tuple(result)


def quantized_slot(slot: PlanSlot) -> PlanSlot:
    if slot.score is None:
        return slot
    return replace(slot, score=float(Decimal(str(slot.score)).quantize(Decimal("0.0001"))))


def quantized_plan(plan: PlanResult) -> PlanResult:
    return replace(
        plan,
        slots=tuple(quantized_slot(slot) for slot in plan.slots),
        future_plans=tuple(quantized_plan(target) for target in plan.future_plans),
    )


def stored_summary(plan: PlanResult) -> dict[str, object]:
    return {
        "timezone": plan.timezone,
        "metrics": asdict(plan.metrics),
        "warnings": [
            {
                "code": item.code,
                "message": item.message,
                "level": item.level,
                "task_id": str(item.task.task_id) if item.task else None,
                "target_date": item.target_date.isoformat() if item.target_date else None,
            }
            for item in plan.warnings
        ],
        "unscheduled": [
            {"task_id": str(item.task.task_id), "reason_codes": list(item.reason_codes)}
            for item in plan.unscheduled
        ],
        "moves": [
            {
                "task_id": str(item.task.task_id),
                "from_date": item.from_date.isoformat(),
                "to_date": item.to_date.isoformat(),
                "reason_code": item.reason_code,
            }
            for item in plan.moves
        ],
    }


def slot_row(schedule: Schedule, slot: PlanSlot) -> ScheduleSlot:
    return ScheduleSlot(
        schedule_id=schedule.id,
        task_id=slot.task.task_id if slot.task is not None else None,
        kind=StoredSlotKind(slot.kind),
        start_at=slot.interval.start,
        end_at=slot.interval.end,
        is_pinned=slot.is_pinned,
        score=Decimal(str(slot.score)) if slot.score is not None else None,
        reason_codes=list(slot.reason_codes),
        explanation=slot.explanation,
    )
