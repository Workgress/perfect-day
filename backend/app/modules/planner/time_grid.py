"""Pure time primitives shared by constraints, energy and the scheduling engine."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.time import (
    LocalTimeError,
    local_day_bounds,
    local_time_candidates,
    local_to_utc,
    parse_timezone,
)
from app.modules.planner.config import (
    GRID_STEP_MINUTES,
    MAX_TASK_DURATION_MINUTES,
    MIN_TASK_DURATION_MINUTES,
)
from app.modules.planner.contracts import Interval, PlanContext, PlanMode


class PlannerTimeError(ValueError):
    """Field-aware domain error; future HTTP adapters own its public encoding."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


@contextmanager
def _time_errors(field: str) -> Iterator[None]:
    try:
        yield
    except LocalTimeError as exc:
        raise PlannerTimeError(field, exc.code, str(exc)) from exc
    except OverflowError as exc:
        raise PlannerTimeError(
            field, "DATE_RANGE_UNSUPPORTED", "Дата выходит за поддерживаемый диапазон"
        ) from exc


@dataclass(frozen=True, slots=True)
class TimeGrid:
    """UTC starts, before duration, occupancy and preview-boundary filtering."""

    day: date
    timezone: str
    mode: PlanMode
    day_bounds: Interval
    work_window: Interval
    available_window: Interval | None
    starts: tuple[datetime, ...]


def make_time_grid(context: PlanContext) -> TimeGrid:
    """Anchor a UTC 15-minute grid to local work_start, never round now down."""
    profile, day = context.profile, context.day
    tz = parse_timezone(profile.timezone)
    with _time_errors("day"):
        day_start, day_end = local_day_bounds(day, tz)
    with _time_errors("work_start"):
        work_start = local_to_utc(datetime.combine(day, profile.work_start), tz)
    with _time_errors("work_end"):
        work_end = local_to_utc(datetime.combine(day, profile.work_end), tz)
    if not day_start <= work_start < work_end <= day_end:
        raise PlannerTimeError(
            "work_end", "WORK_WINDOW_INVALID", "Рабочее окно должно находиться внутри дня"
        )
    work = Interval(work_start, work_end)
    available = None
    starts: list[datetime] = []
    if context.now < work_end:
        available = Interval(max(work_start, context.now), work_end)
        step = timedelta(minutes=GRID_STEP_MINUTES)
        # Integer timedelta arithmetic preserves microseconds and the original anchor.
        index = (available.start - work_start) // step
        at = work_start + index * step
        if at < available.start:
            at += step
        while at < work_end:
            starts.append(at)
            at += step
    return TimeGrid(
        day,
        profile.timezone,
        context.mode,
        Interval(day_start, day_end),
        work,
        available,
        tuple(starts),
    )


def _preview_boundary(at: datetime, tz: ZoneInfo) -> bool:
    local = at.astimezone(tz)
    if local.second or local.microsecond:
        return False
    # PlanPreview has only local clocks: an ambiguous endpoint cannot encode its fold.
    return local_time_candidates(local.replace(tzinfo=None), tz) == (at,)


def candidate_intervals(grid: TimeGrid, duration_min: int) -> tuple[Interval, ...]:
    """Exact elapsed duration, within the work window; no task ranking or placement."""
    if type(duration_min) is not int or not (
        MIN_TASK_DURATION_MINUTES <= duration_min <= MAX_TASK_DURATION_MINUTES
    ):
        raise ValueError("duration_min must be an integer from 5 to 480")
    duration = timedelta(minutes=duration_min)
    tz = parse_timezone(grid.timezone)
    intervals = []
    for start in grid.starts:
        end = start + duration
        if end > grid.work_window.end:
            break
        if grid.mode == "preview" and (
            not _preview_boundary(start, tz)
            or not _preview_boundary(end, tz)
            or end.astimezone(tz).replace(tzinfo=None) - start.astimezone(tz).replace(tzinfo=None)
            != duration
        ):
            continue
        intervals.append(Interval(start, end))
    return tuple(intervals)


def deadline_boundary(deadline: date | None, timezone: str) -> datetime | None:
    """Inclusive calendar deadline -> exclusive next local midnight, without guessing 24h."""
    if deadline is None:
        return None
    if not isinstance(deadline, date) or isinstance(deadline, datetime):
        raise PlannerTimeError("deadline", "INVALID_DATE", "Укажите календарную дату")
    try:
        tz = parse_timezone(timezone)
    except ValueError as exc:
        raise PlannerTimeError("timezone", "TIMEZONE_INVALID", str(exc)) from exc
    with _time_errors("deadline"):
        _, end = local_day_bounds(deadline, tz)
    return end
