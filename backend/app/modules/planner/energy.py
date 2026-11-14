"""Daily energy and interval ranking, independent of persistence and task placement."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import fsum, isfinite

from app.core.time import LocalTimeError, local_to_utc, parse_timezone
from app.modules.biorhythm import engine as biorhythm
from app.modules.biorhythm.types import Cycle
from app.modules.planner.config import (
    CHRONOTYPE_SHIFT_HOURS,
    CIRCADIAN_PROFILES,
    GRID_STEP_MINUTES,
    PEAK_WINDOW_THRESHOLD,
    PREFERRED_START_BONUS,
    PREFERRED_START_TOLERANCE_MINUTES,
    PROFILE_HOURS,
    TASK_CYCLES,
)
from app.modules.planner.contracts import Chronotype, Interval, PlanProfile, PlanTask
from app.modules.planner.engine import PlannerTimeError


@dataclass(frozen=True, slots=True)
class IntervalScore:
    cycle: Cycle | None
    base_score: float
    preference_bonus: float
    circadian_mean: float | None
    cycle_mean: float | None
    peak_fraction: float
    sample_count: int

    @property
    def total(self) -> float:
        return self.base_score + self.preference_bonus


def circadian(cycle: Cycle, local_hour: float, chronotype: Chronotype) -> float:
    """Periodic wall-clock curve in [0, 1], linearly interpolated between knots."""
    cycle = Cycle(cycle)
    if isinstance(local_hour, bool) or not isfinite(local_hour) or not 0 <= local_hour <= 24:
        raise ValueError("local_hour must be finite and between 0 and 24")
    if chronotype not in CHRONOTYPE_SHIFT_HOURS:
        raise ValueError("Unknown chronotype")
    hour = (local_hour - CHRONOTYPE_SHIFT_HOURS[chronotype]) % 24
    index = bisect_right(PROFILE_HOURS, hour) - 1
    left, right = PROFILE_HOURS[index], PROFILE_HOURS[index + 1]
    values = CIRCADIAN_PROFILES[cycle]
    fraction = (hour - left) / (right - left)
    return float(values[index] + fraction * (values[index + 1] - values[index]))


def _samples(interval: Interval) -> tuple[tuple[datetime, float], ...]:
    step = timedelta(minutes=GRID_STEP_MINUTES)
    samples = []
    at = interval.start
    while at < interval.end:
        width = min(step, interval.end - at)
        end = at + width
        samples.append((at + width / 2, width / timedelta(minutes=1)))
        at = end
    return tuple(samples)


def preference_bonus(profile: PlanProfile, task: PlanTask, interval: Interval) -> float:
    """A soft bonus based on elapsed distance from a unique local preferred start."""
    if task.preferred_start is None:
        return 0.0
    try:
        preferred = local_to_utc(
            datetime.combine(task.planned_date, task.preferred_start),
            parse_timezone(profile.timezone),
        )
    except LocalTimeError as exc:
        raise PlannerTimeError("preferred_start", exc.code, str(exc)) from exc
    except OverflowError as exc:
        raise PlannerTimeError(
            "preferred_start", "DATE_RANGE_UNSUPPORTED", "Дата выходит за поддерживаемый диапазон"
        ) from exc
    tolerance = timedelta(minutes=PREFERRED_START_TOLERANCE_MINUTES)
    return PREFERRED_START_BONUS if abs(interval.start - preferred) <= tolerance else 0.0


def score_interval(profile: PlanProfile, task: PlanTask, interval: Interval) -> IntervalScore:
    """Duration-weighted midpoint scores; this function does not check occupancy or capacity."""
    if interval.end - interval.start != timedelta(minutes=task.duration_min):
        raise ValueError("Interval duration must match duration_min exactly")
    tz = parse_timezone(profile.timezone)
    if (
        interval.start.astimezone(tz).date() != task.planned_date
        or (interval.end - timedelta(microseconds=1)).astimezone(tz).date() != task.planned_date
    ):
        raise ValueError("Interval must belong to the task's local planned date")
    samples = _samples(interval)
    values = biorhythm.series(profile.birth_utc, [at for at, _ in samples])
    selected_cycle = TASK_CYCLES.get(task.kind)
    weighted_scores = []
    weighted_circadian = []
    weighted_cycles = []
    peak_weights = []
    for index, (at, weight) in enumerate(samples):
        local = at.astimezone(tz)
        hour = local.hour + local.minute / 60 + (local.second + local.microsecond / 1e6) / 3600
        scores = {}
        for cycle in Cycle:
            curve = circadian(cycle, hour, profile.chronotype)
            value = float(values[cycle][index])
            scores[cycle] = curve * (0.5 + 0.5 * ((value + 1) / 2))
            if cycle == selected_cycle:
                weighted_circadian.append(curve * weight)
                weighted_cycles.append(value * weight)
                if curve >= PEAK_WINDOW_THRESHOLD:
                    peak_weights.append(weight)
        score = 1 - max(scores.values()) if selected_cycle is None else scores[selected_cycle]
        weighted_scores.append(score * weight)
    total_weight = fsum(weight for _, weight in samples)
    return IntervalScore(
        cycle=selected_cycle,
        base_score=fsum(weighted_scores) / total_weight,
        preference_bonus=preference_bonus(profile, task, interval),
        circadian_mean=fsum(weighted_circadian) / total_weight
        if selected_cycle is not None
        else None,
        cycle_mean=fsum(weighted_cycles) / total_weight if selected_cycle is not None else None,
        peak_fraction=fsum(peak_weights) / total_weight,
        sample_count=len(samples),
    )
