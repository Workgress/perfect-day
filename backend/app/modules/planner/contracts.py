"""Internal snapshots and results, not public task CRUD request schemas."""

from dataclasses import dataclass
from datetime import date, datetime, time
from math import isfinite
from typing import Literal, Protocol, get_args
from uuid import UUID

from app.core.time import parse_timezone, to_utc
from app.modules.planner.config import MAX_TASK_DURATION_MINUTES, MIN_TASK_DURATION_MINUTES

type TaskKind = Literal["intellectual", "physical", "creative", "routine"]
type Priority = Literal["high", "medium", "low"]
type TaskState = Literal["pending", "scheduled", "done", "skipped"]
type SchedulingState = Literal["pending", "scheduled"]
type Chronotype = Literal["lark", "dove", "owl"]
type SlotKind = Literal["task", "break", "lunch", "rest"]
type PlanMode = Literal["preview", "initial", "replan"]
type Preservation = Literal["pinned", "done", "started", "past", "system"]
type PlacementChangeKind = Literal["added", "moved", "removed", "updated"]


def _day(value: date, field: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field} must be a calendar date, not a datetime")


def _local_time(value: time, field: str) -> None:
    if not isinstance(value, time) or value.tzinfo is not None:
        raise ValueError(f"{field} must be local time without an offset")


@dataclass(frozen=True, slots=True)
class TaskRef:
    """Exactly one identity: persisted UUID or original zero-based draft index."""

    task_id: UUID | None = None
    task_index: int | None = None

    def __post_init__(self) -> None:
        if (self.task_id is None) == (self.task_index is None):
            raise ValueError("Exactly one of task_id and task_index is required")
        if self.task_id is not None and not isinstance(self.task_id, UUID):
            raise ValueError("task_id must be a UUID")
        if self.task_index is not None and (
            type(self.task_index) is not int or self.task_index < 0
        ):
            raise ValueError("task_index must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class Interval:
    """Half-open UTC interval; normalize before comparing DST folds."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start, end = to_utc(self.start), to_utc(self.end)
        if end <= start:
            raise ValueError("Interval end must be after start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class PlanProfile:
    birth_utc: datetime
    timezone: str
    chronotype: Chronotype
    work_start: time
    work_end: time
    sleep_time: time
    lunch_start: time = time(12)
    lunch_duration_min: int = 60
    work_days: tuple[int, ...] = (1, 2, 3, 4, 5)

    def __post_init__(self) -> None:
        object.__setattr__(self, "birth_utc", to_utc(self.birth_utc))
        parse_timezone(self.timezone)
        if self.chronotype not in get_args(Chronotype.__value__):
            raise ValueError("Unknown chronotype")
        for field in ("work_start", "work_end", "sleep_time", "lunch_start"):
            value = getattr(self, field)
            _local_time(value, field)
            if value.second or value.microsecond:
                raise ValueError(f"{field} must have whole-minute precision")
        if self.work_end <= self.work_start:
            raise ValueError("The work window must not cross midnight")
        if type(self.lunch_duration_min) is not int or not 0 <= self.lunch_duration_min <= 180:
            raise ValueError("lunch_duration_min must be an integer from 0 to 180")
        if any(type(day) is not int or not 1 <= day <= 7 for day in self.work_days):
            raise ValueError("work_days must contain ISO weekdays from 1 to 7")
        if len(set(self.work_days)) != len(self.work_days):
            raise ValueError("work_days must not contain duplicates")
        object.__setattr__(self, "work_days", tuple(self.work_days))


@dataclass(frozen=True, slots=True)
class PlanTask:
    ref: TaskRef
    kind: TaskKind
    duration_min: int
    planned_date: date
    priority: Priority = "medium"
    status: TaskState = "pending"
    preferred_start: time | None = None
    deadline: date | None = None
    is_pinned: bool = False
    pinned_start: datetime | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _day(self.planned_date, "planned_date")
        if self.deadline is not None:
            _day(self.deadline, "deadline")
        for field, values in (
            ("kind", get_args(TaskKind.__value__)),
            ("priority", get_args(Priority.__value__)),
            ("status", get_args(TaskState.__value__)),
        ):
            if getattr(self, field) not in values:
                raise ValueError(f"Unknown {field}")
        if type(self.duration_min) is not int or not (
            MIN_TASK_DURATION_MINUTES <= self.duration_min <= MAX_TASK_DURATION_MINUTES
        ):
            raise ValueError("duration_min must be an integer from 5 to 480")
        if type(self.is_pinned) is not bool:
            raise ValueError("is_pinned must be a boolean")
        if self.is_pinned and self.pinned_start is None:
            raise ValueError("A pinned task needs pinned_start")
        if self.preferred_start is not None:
            _local_time(self.preferred_start, "preferred_start")
        for field in ("pinned_start", "created_at"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, to_utc(value))


@dataclass(frozen=True, slots=True)
class PlanSlot:
    kind: SlotKind
    interval: Interval
    task: TaskRef | None = None
    is_pinned: bool = False
    preservation: Preservation | None = None
    score: float | None = None
    reason_codes: tuple[str, ...] = ()
    explanation: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in get_args(SlotKind.__value__):
            raise ValueError("Unknown slot kind")
        if (self.kind == "task") != (self.task is not None):
            raise ValueError("Only task slots must reference a task")
        if self.kind != "task" and self.is_pinned:
            raise ValueError("System slots cannot be pinned tasks")
        if self.preservation is not None and self.preservation not in get_args(
            Preservation.__value__
        ):
            raise ValueError("Unknown preservation reason")
        if self.score is not None and not isfinite(self.score):
            raise ValueError("score must be finite")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class FutureDay:
    """Explicit occupancy snapshot; an omitted day is unknown, never presumed empty."""

    day: date
    tasks: tuple[PlanTask, ...] = ()
    fixed_slots: tuple[PlanSlot, ...] = ()

    def __post_init__(self) -> None:
        _day(self.day, "day")
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "fixed_slots", tuple(self.fixed_slots))
        refs = {task.ref for task in self.tasks}
        if len(refs) != len(self.tasks):
            raise ValueError("Future task references must be unique")
        if any(task.planned_date != self.day or task.ref.task_id is None for task in self.tasks):
            raise ValueError("Future tasks need persisted IDs and must belong to their day")
        fixed_refs = [slot.task for slot in self.fixed_slots if slot.task is not None]
        if len(set(fixed_refs)) != len(fixed_refs) or any(
            slot.preservation is None or (slot.task is not None and slot.task not in refs)
            for slot in self.fixed_slots
        ):
            raise ValueError(
                "Future reservations must be preserved and reference unique known tasks"
            )


@dataclass(frozen=True, slots=True)
class PlanContext:
    profile: PlanProfile
    day: date
    now: datetime
    tasks: tuple[PlanTask, ...]
    mode: PlanMode
    fixed_slots: tuple[PlanSlot, ...] = ()
    future_days: tuple[FutureDay, ...] = ()
    # False when the remaining-day adapter supplies authoritative lunch/history slots.
    # Future-day probes construct their own context and keep the default profile lunch.
    include_profile_lunch: bool = True

    def __post_init__(self) -> None:
        _day(self.day, "day")
        object.__setattr__(self, "now", to_utc(self.now))
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "fixed_slots", tuple(self.fixed_slots))
        object.__setattr__(self, "future_days", tuple(self.future_days))
        if self.mode not in get_args(PlanMode.__value__):
            raise ValueError("Unknown planning mode")
        if type(self.include_profile_lunch) is not bool:
            raise ValueError("include_profile_lunch must be a boolean")
        refs = {task.ref for task in self.tasks}
        if len(refs) != len(self.tasks):
            raise ValueError("Each task reference must be unique")
        for task in self.tasks:
            if task.planned_date != self.day:
                raise ValueError("Every input task must belong to the planned day")
            if self.mode == "preview" and task.ref.task_index is None:
                raise ValueError("Preview uses original task indexes, not persisted IDs")
            if self.mode == "replan" and task.ref.task_id is None:
                raise ValueError("Replanning uses persisted task IDs")
        if self.mode == "preview" and {task.ref.task_index for task in self.tasks} != set(
            range(len(self.tasks))
        ):
            raise ValueError("Preview indexes must cover the original input without gaps")
        fixed_refs = [slot.task for slot in self.fixed_slots if slot.task is not None]
        if len(set(fixed_refs)) != len(fixed_refs):
            raise ValueError("A task must not have multiple fixed slots")
        for slot in self.fixed_slots:
            if slot.preservation is None:
                raise ValueError("Every fixed slot needs a preservation reason")
            if slot.task is not None and slot.task not in refs:
                raise ValueError("A fixed task slot must reference an input task")
        days = set()
        for future in self.future_days:
            if not 1 <= (future.day - self.day).days <= 7 or future.day in days:
                raise ValueError("Future days must be unique and within the next seven days")
            days.add(future.day)
            for task in future.tasks:
                if task.ref in refs:
                    raise ValueError("A task must not occur on multiple days")
                refs.add(task.ref)


@dataclass(frozen=True, slots=True)
class UnscheduledTask:
    task: TaskRef
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskMove:
    task: TaskRef
    from_date: date
    to_date: date
    reason_code: str


@dataclass(frozen=True, slots=True)
class TaskStatusChange:
    task: TaskRef
    previous: SchedulingState
    next: SchedulingState

    def __post_init__(self) -> None:
        allowed = get_args(SchedulingState.__value__)
        if self.previous not in allowed or self.next not in allowed:
            raise ValueError("The planner only changes pending/scheduled, never done/skipped")
        if self.previous == self.next:
            raise ValueError("A status change must actually change the status")


@dataclass(frozen=True, slots=True)
class PlanWarning:
    code: str
    task: TaskRef | None = None
    target_date: date | None = None
    message: str = ""
    level: Literal["info", "warning", "critical"] = "info"


@dataclass(frozen=True, slots=True)
class PlanMetrics:
    """Whole-day budgets; skipped history remains visible but consumes no work budget."""

    requested_min: int
    planned_min: int
    capacity_min: int
    high_intensity_min: int
    critical_level: int
    load_factor: float
    moved_min: int = 0


@dataclass(frozen=True, slots=True)
class PlanResult:
    day: date
    timezone: str
    algorithm_version: str
    slots: tuple[PlanSlot, ...]
    unscheduled: tuple[UnscheduledTask, ...]
    metrics: PlanMetrics
    moves: tuple[TaskMove, ...] = ()
    status_changes: tuple[TaskStatusChange, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()
    # Only accepted automatic moves have target plans. Advisory probes are never persisted.
    future_plans: tuple["PlanResult", ...] = ()


@dataclass(frozen=True, slots=True)
class PlacementChange:
    """Internal task-placement diff, not a public CRUD response contract."""

    task: TaskRef
    kind: PlacementChangeKind
    before: PlanSlot | None
    after: PlanSlot | None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.task.task_id is None:
            raise ValueError("Placement changes require a persisted task ID")
        if self.before is None and self.after is None:
            raise ValueError("A placement change needs a before or after slot")
        if any(slot.task != self.task for slot in (self.before, self.after) if slot is not None):
            raise ValueError("Changed slots must reference the changed task")
        expected = (
            "added"
            if self.before is None
            else "removed"
            if self.after is None
            else "moved"
            if self.before.interval != self.after.interval
            else "updated"
        )
        if self.kind != expected or self.before == self.after:
            raise ValueError("Placement change kind must describe an actual change")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ReplanResult:
    plan: PlanResult
    changes: tuple[PlacementChange, ...]


class ScheduleBuilder(Protocol):
    """Pure deterministic call. The caller supplies snapshots and owns persistence."""

    def __call__(self, context: PlanContext, /) -> PlanResult: ...
