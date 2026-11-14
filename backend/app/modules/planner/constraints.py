"""Hard placement constraints. No task selection, storage or public CRUD errors."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from math import isfinite

from app.core.time import LocalTimeError, local_to_utc, parse_timezone
from app.modules.planner.config import (
    CONTINUOUS_LONG_LIMIT_MINUTES,
    CONTINUOUS_SHORT_LIMIT_MINUTES,
    HIGH_INTENSITY_CAP_MINUTES,
    HIGH_INTENSITY_KINDS,
    INTENSITY_GAP_MINUTES,
    LONG_BREAK_MINUTES,
    SHORT_BREAK_MINUTES,
)
from app.modules.planner.contracts import (
    Interval,
    PlanContext,
    PlanMetrics,
    PlanSlot,
    PlanTask,
    TaskRef,
)
from app.modules.planner.time_grid import (
    PlannerTimeError,
    TimeGrid,
    candidate_intervals,
    deadline_boundary,
    make_time_grid,
)

MINUTE = timedelta(minutes=1)
MICROSECOND = timedelta(microseconds=1)


class ConstraintError(ValueError):
    def __init__(self, code: str, message: str, task: TaskRef | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.task = task


@dataclass(frozen=True, slots=True)
class PreparedDay:
    context: PlanContext
    grid: TimeGrid
    reserved_slots: tuple[PlanSlot, ...]
    required_breaks: tuple[PlanSlot, ...]
    load_factor: float
    capacity_min: int
    high_intensity_cap_min: int
    reserved_task_min: int
    reserved_high_intensity_min: int

    @property
    def slots(self) -> tuple[PlanSlot, ...]:
        return tuple(
            sorted(
                (*self.reserved_slots, *self.required_breaks), key=lambda slot: slot.interval.start
            )
        )

    @property
    def over_capacity(self) -> bool:
        return self.reserved_task_min > self.capacity_min

    @property
    def over_intensity_limit(self) -> bool:
        return self.reserved_high_intensity_min > self.high_intensity_cap_min


@dataclass(frozen=True, slots=True)
class PlacementCheck:
    reasons: tuple[str, ...]
    required_breaks: tuple[PlanSlot, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.reasons


def overlaps(left: Interval, right: Interval) -> bool:
    return left.start < right.end and right.start < left.end


def _inside(inner: Interval, outer: Interval) -> bool:
    return outer.start <= inner.start < inner.end <= outer.end


def _intersection(left: Interval, right: Interval) -> Interval | None:
    start, end = max(left.start, right.start), min(left.end, right.end)
    return Interval(start, end) if start < end else None


def _uncovered(interval: Interval, covered: tuple[PlanSlot, ...]) -> tuple[Interval, ...]:
    cursor = interval.start
    result = []
    for slot in sorted(covered, key=lambda item: item.interval.start):
        part = _intersection(interval, slot.interval)
        if part is None or part.end <= cursor:
            continue
        if cursor < part.start:
            result.append(Interval(cursor, part.start))
        cursor = max(cursor, part.end)
    if cursor < interval.end:
        result.append(Interval(cursor, interval.end))
    return tuple(result)


def _capacity(work: Interval, slots: tuple[PlanSlot, ...], factor: float) -> int:
    # Subtract the union, including partially overlapping system slots, exactly once.
    systems = tuple(slot for slot in slots if slot.kind != "task")
    usable_us = sum((item.end - item.start) // MICROSECOND for item in _uncovered(work, systems))
    return int(Decimal(usable_us) * Decimal(str(factor)) / Decimal(60_000_000))


def _totals(context: PlanContext, slots: tuple[PlanSlot, ...]) -> tuple[int, int]:
    tasks = {task.ref: task for task in context.tasks}
    total = intense = 0
    for slot in slots:
        if slot.task is not None:
            task = tasks[slot.task]
            if task.status == "skipped":
                continue
            total += task.duration_min
            if task.kind in HIGH_INTENSITY_KINDS:
                intense += task.duration_min
    return total, intense


def _validate_slots(context: PlanContext, grid: TimeGrid, slots: tuple[PlanSlot, ...]) -> None:
    tasks = {task.ref: task for task in context.tasks}
    refs = []
    for slot in slots:
        if not _inside(slot.interval, grid.day_bounds):
            raise ConstraintError(
                "FIXED_OUTSIDE_DAY", "Сохранённый интервал находится вне дня", slot.task
            )
        if slot.task is None:
            continue
        refs.append(slot.task)
        if slot.task not in tasks:
            raise ConstraintError("TASK_CONTEXT_MISMATCH", "Неизвестная задача", slot.task)
        task = tasks[slot.task]
        historical = slot.preservation in {"done", "started", "past"} or (
            slot.preservation == "pinned" and slot.interval.start <= context.now
        )
        if slot.preservation == "system":
            raise ConstraintError(
                "FIXED_TASK_MISMATCH", "Задача не является системным интервалом", slot.task
            )
        if (
            task.status == "skipped" and not historical
        ) or slot.interval.end - slot.interval.start != task.duration_min * MINUTE:
            raise ConstraintError("FIXED_TASK_MISMATCH", "Слот не соответствует задаче", slot.task)
        if slot.is_pinned != task.is_pinned or (
            task.is_pinned and slot.interval.start != task.pinned_start
        ):
            raise ConstraintError(
                "FIXED_TASK_MISMATCH", "Закреплённое начало не совпадает", slot.task
            )
        if slot.preservation is None and slot.interval.start < context.now:
            raise ConstraintError("PAST_START", "Новое размещение находится в прошлом", slot.task)
        if slot.preservation == "pinned" and not task.is_pinned:
            raise ConstraintError("FIXED_TASK_MISMATCH", "Задача не закреплена", slot.task)
        if not historical and not _inside(slot.interval, grid.work_window):
            raise ConstraintError(
                "OUTSIDE_WORK_WINDOW", "Закрепление находится вне рабочего окна", slot.task
            )
        due = None if historical else deadline_boundary(task.deadline, context.profile.timezone)
        if not historical and due is not None and slot.interval.end > due:
            raise ConstraintError("DEADLINE_EXCEEDED", "Закрепление нарушает дедлайн", slot.task)
        if slot.preservation == "done" and task.status != "done":
            raise ConstraintError("FIXED_TASK_MISMATCH", "Задача не выполнена", slot.task)
        if (
            slot.preservation == "started"
            and not slot.interval.start <= context.now < slot.interval.end
        ):
            raise ConstraintError(
                "FIXED_TASK_MISMATCH", "Задача ещё не началась или уже закончилась", slot.task
            )
        if slot.preservation == "past" and slot.interval.end > context.now:
            raise ConstraintError("FIXED_TASK_MISMATCH", "Интервал ещё не завершился", slot.task)
    if len(refs) != len(set(refs)):
        raise ConstraintError("TASK_ALREADY_RESERVED", "Для задачи заданы повторные интервалы")
    ordered = sorted(slots, key=lambda slot: slot.interval.start)
    for left, right in pairwise(ordered):
        if overlaps(left.interval, right.interval):
            raise ConstraintError(
                "INTERVAL_OCCUPIED", "Фиксированные интервалы пересекаются", right.task
            )


def profile_lunch(context: PlanContext, grid: TimeGrid) -> PlanSlot | None:
    """Profile lunch clipped to work; the remaining-day adapter decides what is historical."""
    profile = context.profile
    if profile.lunch_duration_min == 0:
        return None
    try:
        start = local_to_utc(
            datetime.combine(context.day, profile.lunch_start), parse_timezone(profile.timezone)
        )
        interval = Interval(start, start + profile.lunch_duration_min * MINUTE)
    except LocalTimeError as exc:
        raise PlannerTimeError("lunch_start", exc.code, str(exc)) from exc
    except OverflowError as exc:
        raise PlannerTimeError(
            "lunch_start", "DATE_RANGE_UNSUPPORTED", "Обед выходит за диапазон дат"
        ) from exc
    clipped = _intersection(interval, grid.work_window)
    return PlanSlot("lunch", clipped, preservation="system") if clipped is not None else None


def required_break_minutes(left: PlanTask, right: PlanTask, continuous_min: int) -> int:
    if type(continuous_min) is not int or continuous_min < left.duration_min:
        raise ValueError("continuous_min must include the preceding task")
    required = 0
    if left.kind in HIGH_INTENSITY_KINDS and right.kind in HIGH_INTENSITY_KINDS:
        required = INTENSITY_GAP_MINUTES
    if continuous_min > CONTINUOUS_SHORT_LIMIT_MINUTES:
        required = SHORT_BREAK_MINUTES
    if continuous_min > CONTINUOUS_LONG_LIMIT_MINUTES or left.kind == right.kind == "intellectual":
        required = LONG_BREAK_MINUTES
    return required


def _breaks(
    context: PlanContext, slots: tuple[PlanSlot, ...], work_window: Interval
) -> tuple[PlanSlot, ...]:
    tasks = {task.ref: task for task in context.tasks}
    work = sorted(
        (slot for slot in slots if slot.task is not None and tasks[slot.task].status != "skipped"),
        key=lambda slot: slot.interval.start,
    )
    if not work:
        return ()
    systems = tuple(slot for slot in slots if slot.kind != "task")
    result = []
    first_ref = work[0].task
    assert first_ref is not None
    continuous = tasks[first_ref].duration_min
    for left_slot, right_slot in pairwise(work):
        left_ref, right_ref = left_slot.task, right_slot.task
        assert left_ref is not None and right_ref is not None
        left, right = tasks[left_ref], tasks[right_ref]
        gap = right_slot.interval.start - left_slot.interval.end
        required = required_break_minutes(left, right, continuous)
        historical_right = (
            right_slot.preservation is not None and right_slot.interval.start <= context.now
        )
        if not historical_right and gap < required * MINUTE:
            raise ConstraintError(
                "INSUFFICIENT_BREAK", "Недостаточный перерыв между задачами", right.ref
            )
        if required and not historical_right:
            start = max(left_slot.interval.end, context.now, work_window.start)
            end = min(left_slot.interval.end + required * MINUTE, work_window.end)
            if start < end:
                for interval in _uncovered(Interval(start, end), systems):
                    reason = (
                        "BETWEEN_INTELLECTUAL_TASKS"
                        if left.kind == right.kind == "intellectual"
                        else "BREAK_AFTER_LONG_WORK"
                        if continuous > CONTINUOUS_SHORT_LIMIT_MINUTES
                        else "BETWEEN_INTENSIVE_TASKS"
                    )
                    result.append(
                        PlanSlot("break", interval, preservation="system", reason_codes=(reason,))
                    )
        continuous = (
            right.duration_min
            if gap >= SHORT_BREAK_MINUTES * MINUTE
            else continuous + right.duration_min
        )
    return tuple(result)


def prepare_day(
    context: PlanContext, *, load_factor: float = 1.0, rest_intervals: tuple[Interval, ...] = ()
) -> PreparedDay:
    if isinstance(load_factor, bool) or not isfinite(load_factor) or not 0 < load_factor <= 1:
        raise ValueError("load_factor must be finite and in (0, 1]")
    grid = make_time_grid(context)
    slots = list(context.fixed_slots)
    by_ref = {slot.task: slot for slot in slots if slot.task is not None}
    for task in context.tasks:
        if task.status == "done" and task.ref not in by_ref:
            raise ConstraintError(
                "FIXED_SLOT_REQUIRED", "Для выполненной задачи нужен сохранённый слот", task.ref
            )
        if task.is_pinned and task.status != "skipped" and task.ref not in by_ref:
            assert task.pinned_start is not None
            if not grid.day_bounds.start <= task.pinned_start < grid.day_bounds.end or (
                task.duration_min * MINUTE > grid.day_bounds.end - task.pinned_start
            ):
                raise ConstraintError(
                    "FIXED_OUTSIDE_DAY", "Закрепление выходит за границы дня", task.ref
                )
            slots.append(
                PlanSlot(
                    "task",
                    Interval(task.pinned_start, task.pinned_start + task.duration_min * MINUTE),
                    task=task.ref,
                    is_pinned=True,
                    preservation="pinned",
                )
            )
    lunch = profile_lunch(context, grid) if context.include_profile_lunch else None
    if lunch is not None and not any(
        slot.kind == "lunch" and slot.interval == lunch.interval for slot in slots
    ):
        slots.append(lunch)
    for interval in rest_intervals:
        if not _inside(interval, grid.work_window) or interval.start < context.now:
            raise ConstraintError(
                "INVALID_REST_INTERVAL", "Новый отдых должен находиться в доступном рабочем окне"
            )
        if not any(slot.kind == "rest" and slot.interval == interval for slot in slots):
            slots.append(PlanSlot("rest", interval, preservation="system"))
    reserved = tuple(slots)
    _validate_slots(context, grid, reserved)
    breaks = _breaks(context, reserved, grid.work_window)
    _validate_slots(context, grid, reserved + breaks)
    reserved = tuple(sorted(reserved, key=lambda slot: slot.interval.start))
    total, intense = _totals(context, reserved)
    return PreparedDay(
        context=context,
        grid=grid,
        reserved_slots=reserved,
        required_breaks=breaks,
        load_factor=float(load_factor),
        capacity_min=_capacity(grid.work_window, reserved + breaks, load_factor),
        high_intensity_cap_min=int(Decimal(HIGH_INTENSITY_CAP_MINUTES) * Decimal(str(load_factor))),
        reserved_task_min=total,
        reserved_high_intensity_min=intense,
    )


def check_placement(
    prepared: PreparedDay,
    task: PlanTask,
    interval: Interval,
    *,
    placed_slots: tuple[PlanSlot, ...] = (),
) -> PlacementCheck:
    """placed_slots holds accepted tasks; returned required_breaks replaces prior derived breaks."""
    return placement_checker(prepared, placed_slots=placed_slots)(task, interval)


def placement_checker(
    prepared: PreparedDay, *, placed_slots: tuple[PlanSlot, ...] = ()
) -> Callable[[PlanTask, Interval], PlacementCheck]:
    """Validate one immutable accepted snapshot once, then evaluate many candidates.

    Rebuild the checker after accepting a task. Public check_placement still validates every
    externally supplied snapshot, and summarize_day independently validates the final result.
    """
    occupied = prepared.reserved_slots + placed_slots
    _validate_slots(prepared.context, prepared.grid, occupied)
    tasks = {task.ref: task for task in prepared.context.tasks}

    def check(task: PlanTask, interval: Interval) -> PlacementCheck:
        if tasks.get(task.ref) != task:
            raise ConstraintError(
                "TASK_CONTEXT_MISMATCH", "Задача не принадлежит контексту", task.ref
            )
        return _check_candidate(prepared, task, interval, occupied)

    return check


def _check_candidate(
    prepared: PreparedDay, task: PlanTask, interval: Interval, occupied: tuple[PlanSlot, ...]
) -> PlacementCheck:
    context = prepared.context
    reasons = []
    inactive = task.status in {"done", "skipped"}
    already_reserved = any(slot.task == task.ref for slot in occupied)
    if inactive:
        reasons.append("TASK_INACTIVE")
    if already_reserved:
        reasons.append("TASK_ALREADY_RESERVED")
    if interval.end - interval.start != task.duration_min * MINUTE:
        reasons.append("DURATION_MISMATCH")
    if not _inside(interval, prepared.grid.work_window):
        reasons.append("OUTSIDE_WORK_WINDOW")
    if interval.start < context.now:
        reasons.append("PAST_START")
    due = (
        None
        if inactive or already_reserved
        else deadline_boundary(task.deadline, context.profile.timezone)
    )
    if due is not None and interval.end > due:
        reasons.append("DEADLINE_EXCEEDED")
    if any(overlaps(interval, slot.interval) for slot in occupied):
        reasons.append("INTERVAL_OCCUPIED")
    if reasons:
        return PlacementCheck(tuple(reasons))
    prospective = (*occupied, PlanSlot("task", interval, task=task.ref))
    try:
        breaks = _breaks(context, prospective, prepared.grid.work_window)
    except ConstraintError as exc:
        return PlacementCheck((exc.code,))
    capacity = _capacity(prepared.grid.work_window, prospective + breaks, prepared.load_factor)
    total, intense = _totals(context, prospective)
    if total > capacity:
        reasons.append("DAY_CAPACITY_EXCEEDED")
    if task.kind in HIGH_INTENSITY_KINDS and intense > prepared.high_intensity_cap_min:
        reasons.append("INTENSITY_CAPACITY_EXCEEDED")
    return PlacementCheck(tuple(reasons), breaks if not reasons else ())


def feasible_intervals(
    prepared: PreparedDay, task: PlanTask, *, placed_slots: tuple[PlanSlot, ...] = ()
) -> tuple[Interval, ...]:
    if task not in prepared.context.tasks:
        raise ConstraintError("TASK_CONTEXT_MISMATCH", "Задача не принадлежит контексту", task.ref)
    check = placement_checker(prepared, placed_slots=placed_slots)
    return tuple(
        interval
        for interval in candidate_intervals(prepared.grid, task.duration_min)
        if check(task, interval).allowed
    )


def summarize_day(
    prepared: PreparedDay,
    *,
    placed_slots: tuple[PlanSlot, ...] = (),
    required_breaks: tuple[PlanSlot, ...] | None = None,
    critical_level: int = 0,
) -> PlanMetrics:
    """Validate the final slot snapshot and measure its actual duration budgets."""
    if type(critical_level) is not int or not 0 <= critical_level <= 3:
        raise ValueError("critical_level must be an integer from 0 to 3")
    breaks = prepared.required_breaks if required_breaks is None else required_breaks
    slots = (*prepared.reserved_slots, *placed_slots, *breaks)
    _validate_slots(prepared.context, prepared.grid, slots)
    planned, intense = _totals(prepared.context, slots)
    return PlanMetrics(
        requested_min=sum(
            task.duration_min for task in prepared.context.tasks if task.status != "skipped"
        ),
        planned_min=planned,
        capacity_min=_capacity(prepared.grid.work_window, slots, prepared.load_factor),
        high_intensity_min=intense,
        critical_level=critical_level,
        load_factor=prepared.load_factor,
    )
