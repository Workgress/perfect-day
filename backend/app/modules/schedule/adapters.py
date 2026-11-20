"""Conversions between existing ORM rows and immutable planner snapshots."""

from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import TypeAdapter

from app.core.errors import AppError
from app.modules.planner.contracts import (
    Interval,
    PlanProfile,
    PlanResult,
    PlanSlot,
    PlanTask,
    Preservation,
    TaskRef,
    TaskState,
)
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.schedule.models import SlotKind as StoredSlotKind
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.schemas import ProfileState
from app.modules.users.service import ProfileIncompleteError

_PLAN_RESULT = TypeAdapter(PlanResult)


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
        actual_start=row.actual_start,
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
        "schema_version": 3,
        "slot_count": len(plan.slots),
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
            {
                "task_id": str(item.task.task_id),
                "reason_codes": list(item.reason_codes),
                "explanation": item.explanation,
            }
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
        "recommendations": [
            {
                "task_id": str(item.task.task_id),
                "from_date": item.from_date.isoformat(),
                "to_date": item.to_date.isoformat(),
                "reason_code": item.reason_code,
                "explanation": item.explanation,
            }
            for item in plan.recommendations
        ],
        "status_changes": [
            {"task_id": str(item.task.task_id), "previous": item.previous, "next": item.next}
            for item in plan.status_changes
        ],
        "slot_preservations": [
            {
                "task_id": str(item.task.task_id) if item.task is not None else None,
                "kind": item.kind,
                "start_at": item.interval.start.isoformat(),
                "end_at": item.interval.end.isoformat(),
                "preservation": item.preservation,
            }
            for item in plan.slots
            if item.preservation is not None
        ],
        "future_schedule_ids": [],
    }


def restore_plan(schedule: Schedule, future_plans: tuple[PlanResult, ...] = ()) -> PlanResult:
    try:
        summary = schedule.summary
        version = summary.get("schema_version", 1)
        if version not in {1, 2, 3}:
            raise ValueError("Unsupported stored plan schema")
        if version >= 2:
            for field in (
                "slot_count",
                "status_changes",
                "slot_preservations",
                "future_schedule_ids",
            ):
                if field not in summary:
                    raise ValueError("Incomplete stored plan")
            if summary["slot_count"] != len(schedule.slots):
                raise ValueError("Stored plan slots are incomplete")
        if version == 3 and "recommendations" not in summary:
            raise ValueError("Stored plan recommendations are incomplete")
        preservations = {
            (
                item["kind"],
                datetime.fromisoformat(item["start_at"]),
                datetime.fromisoformat(item["end_at"]),
                UUID(item["task_id"]) if item["task_id"] is not None else None,
            ): item["preservation"]
            for item in summary.get("slot_preservations", [])
        }
        slots = []
        for row in schedule.slots:
            key = (row.kind.value, row.start_at, row.end_at, row.task_id)
            if row.kind == StoredSlotKind.TASK and row.task_id is None:
                raise ValueError("Stored task slot has no identity")
            slots.append(
                PlanSlot(
                    row.kind.value,
                    Interval(row.start_at, row.end_at),
                    TaskRef(task_id=row.task_id) if row.task_id is not None else None,
                    is_pinned=row.is_pinned,
                    score=float(row.score) if row.score is not None else None,
                    reason_codes=tuple(row.reason_codes),
                    explanation=row.explanation,
                    preservation=cast(Preservation | None, preservations.pop(key, None)),
                )
            )
        if preservations:
            raise ValueError("Preservation metadata has no matching slot")
        result = _PLAN_RESULT.validate_python(
            {
                "day": schedule.date,
                "timezone": summary["timezone"],
                "algorithm_version": schedule.algorithm_version,
                "slots": tuple(sorted(slots, key=lambda item: item.interval.start)),
                "metrics": summary["metrics"],
                "unscheduled": [
                    {
                        "task": {"task_id": item["task_id"]},
                        "reason_codes": item["reason_codes"],
                        "explanation": item.get("explanation"),
                    }
                    for item in summary["unscheduled"]
                ],
                "warnings": [
                    {**item, "task": {"task_id": item["task_id"]} if item["task_id"] else None}
                    for item in summary["warnings"]
                ],
                "moves": [
                    {**item, "task": {"task_id": item["task_id"]}} for item in summary["moves"]
                ],
                "recommendations": [
                    {**item, "task": {"task_id": item["task_id"]}}
                    for item in summary.get("recommendations", [])
                ],
                "status_changes": [
                    {**item, "task": {"task_id": item["task_id"]}}
                    for item in summary.get("status_changes", [])
                ],
                "future_plans": future_plans,
            }
        )
        if (
            result.metrics.critical_level != schedule.critical_level
            or Decimal(str(result.metrics.load_factor)).quantize(Decimal("0.001"))
            != schedule.load_factor
            or len(summary.get("future_schedule_ids", [])) != len(future_plans)
            or {move.to_date for move in result.moves} != {plan.day for plan in future_plans}
        ):
            raise ValueError("Stored plan metadata does not match its versions")
        return result
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AppError(
            409, "SCHEDULE_RESULT_INCOMPLETE", "Сохранённый результат расписания неполон"
        ) from exc


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
