"""Deterministic greedy scheduling over immutable task and profile snapshots."""

from datetime import UTC, datetime, time

from app.core.time import parse_timezone
from app.modules.biorhythm import engine as biorhythm
from app.modules.planner.config import (
    ALGORITHM_VERSION,
    PRIORITY_ORDER,
    SAME_KIND_PENALTY,
    TASK_INTENSITY,
)
from app.modules.planner.constraints import check_placement, prepare_day, summarize_day
from app.modules.planner.contracts import (
    Interval,
    PlanContext,
    PlanResult,
    PlanSlot,
    PlanTask,
    TaskKind,
    TaskRef,
    TaskStatusChange,
    UnscheduledTask,
)
from app.modules.planner.energy import IntervalScore, score_interval
from app.modules.planner.time_grid import PlannerTimeError as PlannerTimeError
from app.modules.planner.time_grid import TimeGrid as TimeGrid
from app.modules.planner.time_grid import candidate_intervals as candidate_intervals
from app.modules.planner.time_grid import deadline_boundary as deadline_boundary
from app.modules.planner.time_grid import make_time_grid as make_time_grid


def _task_order(task: PlanTask) -> tuple[int, int, int, datetime, int, int]:
    if task.ref.task_id is not None:
        created = (
            task.created_at if task.created_at is not None else datetime.min.replace(tzinfo=UTC)
        )
        identity = (0, task.ref.task_id.int)
    else:
        assert task.ref.task_index is not None
        created = datetime.min.replace(tzinfo=UTC)
        identity = (1, task.ref.task_index)
    return (
        PRIORITY_ORDER[task.priority],
        -TASK_INTENSITY[task.kind],
        -task.duration_min,
        created,
        identity[0],
        identity[1],
    )


def sort_tasks(tasks: tuple[PlanTask, ...]) -> tuple[PlanTask, ...]:
    """Priority, intensity, duration, creation time and stable identity; never input order."""
    return tuple(sorted(tasks, key=_task_order))


def _repetition_penalty(
    task: PlanTask, interval: Interval, slots: tuple[PlanSlot, ...], tasks: dict[TaskRef, PlanTask]
) -> float:
    work = [slot for slot in slots if slot.task is not None]
    left = max(
        (slot for slot in work if slot.interval.end <= interval.start),
        key=lambda slot: slot.interval.end,
        default=None,
    )
    right = min(
        (slot for slot in work if slot.interval.start >= interval.end),
        key=lambda slot: slot.interval.start,
        default=None,
    )
    matches = 0
    for neighbor in (left, right):
        if (
            neighbor is not None
            and neighbor.task is not None
            and tasks[neighbor.task].kind == task.kind
        ):
            matches += 1
    return SAME_KIND_PENALTY * matches


def build_schedule(
    context: PlanContext, *, load_factor: float = 1.0, rest_intervals: tuple[Interval, ...] = ()
) -> PlanResult:
    """Select whole-task intervals, retain reservations and report every unplaced active task.

    A greedy result is deterministic, not a global optimum. Equal ratings choose the earliest
    UTC start. Critical-day load/move policies and text explanations are added in stage 6.
    The caller owns persistence, status updates and initial-plan completeness checks.
    """
    prepared = prepare_day(context, load_factor=load_factor, rest_intervals=rest_intervals)
    tasks = {task.ref: task for task in context.tasks}
    reserved_refs = {slot.task for slot in prepared.reserved_slots if slot.task is not None}
    pending = tuple(
        task
        for task in context.tasks
        if task.status in {"pending", "scheduled"} and task.ref not in reserved_refs
    )
    placed: tuple[PlanSlot, ...] = ()
    breaks = prepared.required_breaks
    unscheduled = []
    ratings: dict[tuple[TaskKind, int, time | None, Interval], IntervalScore] = {}
    for task in sort_tasks(pending):
        best: PlanSlot | None = None
        best_breaks: tuple[PlanSlot, ...] = ()
        failures: set[str] = set()
        candidates = candidate_intervals(prepared.grid, task.duration_min)
        for interval in candidates:
            check = check_placement(prepared, task, interval, placed_slots=placed)
            if not check.allowed:
                failures.update(check.reasons)
                continue
            key = (task.kind, task.duration_min, task.preferred_start, interval)
            if key not in ratings:
                ratings[key] = score_interval(context.profile, task, interval)
            rating = ratings[key]
            penalty = _repetition_penalty(task, interval, prepared.reserved_slots + placed, tasks)
            score = rating.total - penalty
            if best is None or best.score is None or score > best.score:
                reasons = ["ENERGY_RANKED"]
                if rating.preference_bonus:
                    reasons.append("PREFERRED_START")
                if penalty:
                    reasons.append("TYPE_REPETITION")
                best = PlanSlot(
                    "task", interval, task=task.ref, score=score, reason_codes=tuple(reasons)
                )
                best_breaks = check.required_breaks
        if best is None:
            if not candidates:
                failures.add(
                    "NO_AVAILABLE_TIME" if not prepared.grid.starts else "NO_CONTIGUOUS_WINDOW"
                )
            unscheduled.append(
                UnscheduledTask(task.ref, ("NO_FEASIBLE_INTERVAL", *sorted(failures)))
            )
        else:
            placed = (*placed, best)
            breaks = best_breaks
    slots = tuple(
        sorted((*prepared.reserved_slots, *placed, *breaks), key=lambda slot: slot.interval.start)
    )
    scheduled = {slot.task for slot in slots if slot.task is not None}
    status_changes = []
    if context.mode != "preview":
        for task in sort_tasks(context.tasks):
            if task.status == "pending" and task.ref in scheduled:
                status_changes.append(TaskStatusChange(task.ref, "pending", "scheduled"))
            elif task.status == "scheduled" and task.ref not in scheduled:
                status_changes.append(TaskStatusChange(task.ref, "scheduled", "pending"))
    critical = biorhythm.critical_info(
        context.profile.birth_utc, context.day, parse_timezone(context.profile.timezone)
    )
    return PlanResult(
        day=context.day,
        timezone=context.profile.timezone,
        algorithm_version=ALGORITHM_VERSION,
        slots=slots,
        unscheduled=tuple(unscheduled),
        metrics=summarize_day(
            prepared, placed_slots=placed, required_breaks=breaks, critical_level=critical.level
        ),
        status_changes=tuple(status_changes),
    )
