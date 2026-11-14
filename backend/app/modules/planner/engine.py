"""Deterministic greedy scheduling over immutable task and profile snapshots."""

from dataclasses import replace
from datetime import UTC, date, datetime, time

from app.modules.planner.config import (
    ALGORITHM_VERSION,
    PRIORITY_ORDER,
    SAME_KIND_PENALTY,
    TASK_CYCLES,
    TASK_INTENSITY,
)
from app.modules.planner.constraints import PreparedDay, check_placement, summarize_day
from app.modules.planner.contracts import (
    FutureDay,
    Interval,
    PlanContext,
    PlanResult,
    PlanSlot,
    PlanTask,
    PlanWarning,
    TaskKind,
    TaskMove,
    TaskRef,
    TaskStatusChange,
    UnscheduledTask,
)
from app.modules.planner.energy import IntervalScore, score_interval
from app.modules.planner.explanations import explain_move, explain_slots
from app.modules.planner.policy import day_policy, prepare_policy_day
from app.modules.planner.recommendations import (
    critical_move_unavailable,
    day_recommendations,
    move_recommendation,
    overloaded,
)
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


def _build_day(
    prepared: PreparedDay,
    *,
    critical_level: int,
    excluded: frozenset[TaskRef] = frozenset(),
    rest_shortfall: int = 0,
) -> PlanResult:
    context = prepared.context
    tasks = {task.ref: task for task in context.tasks}
    reserved_refs = {slot.task for slot in prepared.reserved_slots if slot.task is not None}
    pending = tuple(
        task
        for task in context.tasks
        if task.status in {"pending", "scheduled"} and task.ref not in reserved_refs | excluded
    )
    placed: tuple[PlanSlot, ...] = ()
    breaks = prepared.required_breaks
    unscheduled = []
    ratings: dict[tuple[TaskKind, int, time | None, Interval], IntervalScore] = {}
    for task in sort_tasks(pending):
        if rest_shortfall:
            unscheduled.append(UnscheduledTask(task.ref, ("CRITICAL_REST_UNAVAILABLE",)))
            continue
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
    scheduled = {slot.task for slot in slots if slot.task is not None} | excluded
    status_changes = []
    if context.mode != "preview":
        for task in sort_tasks(context.tasks):
            if task.status == "pending" and task.ref in scheduled:
                status_changes.append(TaskStatusChange(task.ref, "pending", "scheduled"))
            elif task.status == "scheduled" and task.ref not in scheduled:
                status_changes.append(TaskStatusChange(task.ref, "scheduled", "pending"))
    return PlanResult(
        day=context.day,
        timezone=context.profile.timezone,
        algorithm_version=ALGORITHM_VERSION,
        slots=slots,
        unscheduled=tuple(unscheduled),
        metrics=summarize_day(
            prepared, placed_slots=placed, required_breaks=breaks, critical_level=critical_level
        ),
        status_changes=tuple(status_changes),
    )


def _find_target(
    context: PlanContext,
    task: PlanTask,
    days: dict[date, FutureDay],
    *,
    prefer_peak: bool = False,
) -> tuple[FutureDay, PlanResult] | None:
    """Probe supplied occupancy only. Never displace a resident task into unscheduled."""
    candidates = []
    for day, snapshot in sorted(days.items()):
        if day.isoweekday() not in context.profile.work_days:
            continue
        if task.deadline is not None and day > task.deadline:
            continue
        policy = day_policy(context.profile, day)
        cycle = TASK_CYCLES.get(task.kind)
        value = policy.value(cycle) if cycle is not None else 0.0
        if policy.critical.level or value < 0:
            continue
        candidates.append((snapshot, value))
    if prefer_peak:
        candidates.sort(key=lambda item: (item[1] < 0.5, item[0].day))
    for snapshot, _ in candidates:
        proposed = replace(
            snapshot, tasks=(*snapshot.tasks, replace(task, planned_date=snapshot.day))
        )
        probe = PlanContext(
            context.profile,
            proposed.day,
            context.now,
            proposed.tasks,
            "replan",
            proposed.fixed_slots,
        )
        result = build_schedule(probe)
        if not result.unscheduled and any(slot.task == task.ref for slot in result.slots):
            return proposed, result
    return None


def build_schedule(
    context: PlanContext,
    *,
    load_factor: float | None = None,
    rest_intervals: tuple[Interval, ...] = (),
) -> PlanResult:
    """Pure deterministic plan with critical-day budgets, moves and recommendations.

    Only replan mode proposes automatic moves, and only to explicitly supplied occupied-day
    snapshots. The returned future plans belong to the same atomic write as those moves.
    Preview/initial never move tasks to conceal an incomplete first plan. Persistence, status
    updates and concurrency checks remain the caller's responsibility (integration stage 8).
    An explicit load_factor is a budget override; it never disables mandatory critical rest.
    """
    policy = day_policy(context.profile, context.day)
    prepared, shortfall = prepare_policy_day(
        context, policy, load_factor=load_factor, rest_intervals=rest_intervals
    )
    fixed = {slot.task for slot in prepared.reserved_slots if slot.task is not None}
    days = {snapshot.day: snapshot for snapshot in context.future_days}
    target_plans: dict[date, PlanResult] = {}
    moves = []
    unavailable = []
    if context.mode == "replan" and policy.critical.level:
        for task in sort_tasks(context.tasks):
            if (
                task.status not in {"pending", "scheduled"}
                or task.is_pinned
                or task.ref in fixed
                or task.kind not in {"intellectual", "physical"}
                or (task.priority != "high" and task.duration_min < 60)
            ):
                continue
            found = _find_target(context, task, days)
            if found is None:
                unavailable.append(critical_move_unavailable(task.ref))
                continue
            snapshot, target = found
            days[snapshot.day] = snapshot
            target_plans[snapshot.day] = target
            moves.append(TaskMove(task.ref, context.day, snapshot.day, "MOVED_FROM_CRITICAL_DAY"))
    moved = frozenset(move.task for move in moves)
    result = _build_day(
        prepared, critical_level=policy.critical.level, excluded=moved, rest_shortfall=shortfall
    )
    result = replace(
        result,
        slots=explain_slots(context, result.slots, policy),
        metrics=replace(
            result.metrics,
            moved_min=sum(task.duration_min for task in context.tasks if task.ref in moved),
        ),
    )
    tasks = {task.ref: task for task in context.tasks}
    warnings = [*day_recommendations(context, result, policy, shortfall), *unavailable]
    for move in moves:
        target = target_plans[move.to_date]
        message = move_recommendation(
            tasks[move.task], target, day_policy(context.profile, target.day), automatic=True
        )
        warnings.append(
            PlanWarning(move.reason_code, task=move.task, target_date=move.to_date, message=message)
        )
    future_plans = []
    for _day, target in sorted(target_plans.items()):
        future_plans.append(
            replace(
                target,
                slots=tuple(
                    explain_move(slot, context.day) if slot.task in moved else slot
                    for slot in target.slots
                ),
                status_changes=tuple(
                    change for change in target.status_changes if change.task not in moved
                ),
            )
        )
    # Advisory probes share a tentative occupancy snapshot to avoid collectively overbooking
    # a suggested day. They never enter moves or future_plans and never alter input objects.
    advice_days = dict(days)
    reserved = fixed | moved
    unplaced = {item.task for item in result.unscheduled}
    if context.mode != "preview":
        for task in sort_tasks(context.tasks):
            if (
                task.ref in reserved
                or task.ref.task_id is None
                or task.status not in {"pending", "scheduled"}
                or task.is_pinned
                or not (task.ref in unplaced or (overloaded(result) and task.priority == "low"))
            ):
                continue
            found = _find_target(context, task, advice_days, prefer_peak=True)
            if found is not None:
                snapshot, target = found
                advice_days[snapshot.day] = snapshot
                warnings.append(
                    PlanWarning(
                        "SUGGESTED_MOVE",
                        task=task.ref,
                        target_date=target.day,
                        message=move_recommendation(
                            task, target, day_policy(context.profile, target.day), automatic=False
                        ),
                        level="warning",
                    )
                )
    return replace(
        result,
        moves=tuple(moves),
        warnings=tuple(warnings),
        future_plans=tuple(future_plans),
    )
