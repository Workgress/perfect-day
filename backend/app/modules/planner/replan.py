"""Pure remaining-day adapter: retain history, rebuild future work and describe changes."""

from dataclasses import replace
from datetime import timedelta
from itertools import pairwise

from app.modules.planner.constraints import ConstraintError, overlaps, profile_lunch
from app.modules.planner.contracts import (
    Interval,
    PlacementChange,
    PlacementChangeKind,
    PlanContext,
    PlanResult,
    PlanSlot,
    Preservation,
    ReplanResult,
)
from app.modules.planner.engine import build_schedule
from app.modules.planner.explanations import explain_slots
from app.modules.planner.policy import day_policy
from app.modules.planner.time_grid import TimeGrid, make_time_grid


def _validate_previous(slots: tuple[PlanSlot, ...], grid: TimeGrid) -> None:
    refs = set()
    for slot in slots:
        if (
            not grid.day_bounds.start
            <= slot.interval.start
            < slot.interval.end
            <= grid.day_bounds.end
        ):
            raise ConstraintError(
                "FIXED_OUTSIDE_DAY", "Прежний интервал находится вне дня", slot.task
            )
        if slot.task is not None:
            if slot.task.task_id is None:
                raise ConstraintError("TASK_CONTEXT_MISMATCH", "Нужен сохранённый UUID", slot.task)
            if slot.task in refs:
                raise ConstraintError(
                    "TASK_ALREADY_RESERVED", "В прежнем плане задача повторяется", slot.task
                )
            refs.add(slot.task)
    for left, right in pairwise(sorted(slots, key=lambda item: item.interval.start)):
        if overlaps(left.interval, right.interval):
            raise ConstraintError("INTERVAL_OCCUPIED", "Прежние интервалы пересекаются", right.task)


def preserve_reservations(
    context: PlanContext, previous: tuple[PlanSlot, ...]
) -> tuple[PlanSlot, ...]:
    """Select current hard reservations from a previous snapshot, without creating new systems."""
    tasks = {task.ref: task for task in context.tasks}
    selected = list(context.fixed_slots)
    for slot in previous:
        retained: PlanSlot | None = None
        if slot.task is None:
            if slot.interval.start <= context.now:
                retained = replace(slot, preservation="system")
        else:
            task = tasks.get(slot.task)
            if task is None:
                if slot.interval.start <= context.now:
                    raise ConstraintError(
                        "HISTORY_TASK_REQUIRED",
                        "Для сохранения истории нужен снимок задачи",
                        slot.task,
                    )
                continue
            if task.status == "done" or slot.interval.start <= context.now:
                preservation: Preservation = (
                    "done"
                    if task.status == "done"
                    else "past"
                    if slot.interval.end <= context.now
                    else "started"
                )
                # Pin flags may change, but a begun or completed interval cannot be moved.
                # prepare_day also checks unchanged duration and a pinned start match.
                retained = replace(slot, preservation=preservation, is_pinned=task.is_pinned)
            elif (
                task.status != "skipped"
                and task.is_pinned
                and slot.is_pinned
                and slot.interval.start == task.pinned_start
                and slot.interval.end - slot.interval.start == timedelta(minutes=task.duration_min)
            ):
                retained = replace(slot, preservation="pinned")
        if retained is None:
            continue
        matching = next(
            (
                item
                for item in selected
                if (retained.task is not None and item.task == retained.task)
                or (
                    retained.task is None
                    and item.kind == retained.kind
                    and item.interval == retained.interval
                )
            ),
            None,
        )
        if matching is None:
            selected.append(retained)
        elif replace(matching, preservation=None) != replace(retained, preservation=None):
            raise ConstraintError(
                "FIXED_TASK_MISMATCH",
                "Фиксированный интервал противоречит прежнему плану",
                retained.task,
            )
    return tuple(sorted(selected, key=lambda item: item.interval.start))


def _validate_pin_history(context: PlanContext, previous: tuple[PlanSlot, ...]) -> None:
    for task in context.tasks:
        if (
            task.status not in {"pending", "scheduled"}
            or not task.is_pinned
            or task.pinned_start is None
            or task.pinned_start >= context.now
        ):
            continue
        if not any(
            slot.task == task.ref and slot.interval.start == task.pinned_start
            for slot in (*previous, *context.fixed_slots)
        ):
            raise ConstraintError(
                "PAST_START", "Новое закрепление не может начинаться в прошлом", task.ref
            )


def _with_lunch(
    context: PlanContext, grid: TimeGrid, preserved: tuple[PlanSlot, ...]
) -> tuple[PlanSlot, ...]:
    # A begun/taken lunch is authoritative even after profile edits; never book it twice.
    if not context.include_profile_lunch or any(slot.kind == "lunch" for slot in preserved):
        return preserved
    lunch = profile_lunch(context, grid)
    if lunch is None or lunch.interval.end <= context.now:
        return preserved
    if lunch.interval.start < context.now:
        lunch = replace(lunch, interval=Interval(context.now, lunch.interval.end))
    explained = explain_slots(
        replace(context, fixed_slots=()), (lunch,), day_policy(context.profile, context.day)
    )
    return (*preserved, *explained)


def _changes(
    context: PlanContext, previous: tuple[PlanSlot, ...], result: PlanResult
) -> tuple[PlacementChange, ...]:
    before = {slot.task: slot for slot in previous if slot.task is not None}
    tasks = {task.ref: task for task in context.tasks}
    relevant = set(before) | set(tasks)
    after = {
        slot.task: slot
        for plan in (result, *result.future_plans)
        for slot in plan.slots
        if slot.task is not None and slot.task in relevant
    }
    unplaced = {item.task: item.reason_codes for item in result.unscheduled}
    changes = []
    for ref in sorted(set(before) | set(after), key=lambda item: str(item.task_id)):
        old, new = before.get(ref), after.get(ref)
        # Preservation is recalculated at each now; it is not a visible placement change.
        if (
            old is not None
            and new is not None
            and replace(old, preservation=None) == replace(new, preservation=None)
        ):
            continue
        kind: PlacementChangeKind
        reasons: tuple[str, ...]
        if old is None:
            kind, reasons = "added", ("TASK_PLACED",)
        elif new is None:
            kind = "removed"
            task = tasks.get(ref)
            reasons = (
                ("TASK_REMOVED",)
                if task is None
                else ("TASK_SKIPPED",)
                if task.status == "skipped"
                else unplaced[ref]
            )
        else:
            kind = "moved" if old.interval != new.interval else "updated"
            reasons = ("REPLANNED",) if kind == "moved" else ("PLACEMENT_UPDATED",)
        if new is not None:
            reasons = tuple(dict.fromkeys((*reasons, *new.reason_codes)))
        changes.append(PlacementChange(ref, kind, old, new, reasons))
    return tuple(changes)


def replan_remaining_day(
    context: PlanContext, previous_slots: tuple[PlanSlot, ...] = ()
) -> ReplanResult:
    """Rebuild around past/started/done/current pins, using current task/profile snapshots.

    Input slots are the previous active schedule in the current local day. Include task
    snapshots referenced by history, even soft-deleted rows; missing historical references
    and edits invalidating their duration/start fail instead of erasing or rewriting history.
    Future deleted/skipped placements disappear. Future pin changes follow the current task.
    Exactly at a saved start the task/system block counts as begun; exactly at its end, past.

    This function performs no CRUD, transactions, notification dispatch or version changes.
    Its internal diff covers source tasks (including cross-day moves); future resident tasks
    remain described by each returned target plan. Integration owns their persistence.
    """
    if context.mode != "replan":
        raise ValueError("Remaining-day replanning requires replan mode")
    previous = tuple(previous_slots)
    grid = make_time_grid(context)
    _validate_previous(previous, grid)
    _validate_pin_history(context, previous)
    preserved = _with_lunch(context, grid, preserve_reservations(context, previous))
    prepared = replace(context, fixed_slots=preserved, include_profile_lunch=False)
    plan = build_schedule(prepared)
    return ReplanResult(plan, _changes(context, previous, plan))
