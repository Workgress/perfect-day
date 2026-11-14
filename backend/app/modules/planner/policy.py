"""Critical-day budgets and mandatory rest, using the shared biorhythm mathematics."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import combinations

from app.core.time import LocalTimeError, local_time_candidates, parse_timezone
from app.modules.biorhythm import engine as biorhythm
from app.modules.biorhythm.types import CriticalInfo, Cycle, Phase
from app.modules.planner.constraints import PreparedDay, overlaps, prepare_day
from app.modules.planner.contracts import Interval, PlanContext, PlanProfile
from app.modules.planner.time_grid import PlannerTimeError, candidate_intervals


@dataclass(frozen=True, slots=True)
class DayPolicy:
    critical: CriticalInfo
    cycle_values: tuple[tuple[Cycle, float], ...]
    minimum_cycles: tuple[Cycle, ...]
    load_factor: float
    rest_count: int

    def value(self, cycle: Cycle) -> float:
        return dict(self.cycle_values)[cycle]


def day_policy(profile: PlanProfile, day: date) -> DayPolicy:
    """Whole local day crossings; phase/load reference is local noon, like bio forecast.

    On a repeated noon choose its earlier UTC occurrence. Never guess a missing noon.
    More than one minimum still adds only one 0.9 multiplier.
    """
    tz = parse_timezone(profile.timezone)
    try:
        moments = local_time_candidates(datetime.combine(day, time(12)), tz)
    except OverflowError as exc:
        raise PlannerTimeError(
            "day", "DATE_RANGE_UNSUPPORTED", "Local noon is out of range"
        ) from exc
    if not moments:
        raise PlannerTimeError("day", "LOCAL_TIME_NONEXISTENT", "Local noon does not exist")
    state = biorhythm.snapshot(profile.birth_utc, moments[0])
    try:
        critical = biorhythm.critical_info(profile.birth_utc, day, tz)
    except (LocalTimeError, OverflowError) as exc:
        code = exc.code if isinstance(exc, LocalTimeError) else "DATE_RANGE_UNSUPPORTED"
        raise PlannerTimeError("day", code, str(exc)) from exc
    minima = tuple(cycle for cycle, value in state.cycles.items() if value.phase == Phase.MINIMUM)
    factor = (Decimal("1"), Decimal("0.8"), Decimal("0.65"), Decimal("0.5"))[critical.level]
    if minima:
        factor *= Decimal("0.9")
    return DayPolicy(
        critical,
        tuple((cycle, value.value) for cycle, value in state.cycles.items()),
        minima,
        float(factor),
        max(0, critical.level - 1),
    )


def prepare_policy_day(
    context: PlanContext,
    policy: DayPolicy,
    *,
    load_factor: float | None = None,
    rest_intervals: tuple[Interval, ...] = (),
) -> tuple[PreparedDay, int]:
    """Reserve distinct 30-minute rests before ranking tasks; retain immutable history.

    Rest centers are spread through real elapsed work time. Existing rest counts, including
    rest already taken. Derived breaks may be fulfilled by rest and are recalculated.
    A shortfall is returned explicitly so the caller cannot add work in its place.
    """
    factor = policy.load_factor if load_factor is None else load_factor
    prepared = prepare_day(context, load_factor=factor, rest_intervals=rest_intervals)
    existing = sum(
        (slot.interval.end - slot.interval.start) // timedelta(minutes=30)
        for slot in prepared.reserved_slots
        if slot.kind == "rest"
    )
    missing = max(0, policy.rest_count - existing)
    if not missing:
        return prepared, 0
    choices = tuple(
        interval
        for interval in candidate_intervals(prepared.grid, 30)
        if not any(overlaps(interval, slot.interval) for slot in prepared.reserved_slots)
    )
    work = prepared.grid.work_window
    # At most two blocks: select jointly so the first choice cannot fragment the only
    # available hour into two unusable 15-minute pieces. Partial rest is still retained.
    for count in range(missing, 0, -1):
        centers = tuple(
            work.start + (work.end - work.start) * (index + 1) / (count + 1)
            for index in range(count)
        )
        best = min(
            (
                group
                for group in combinations(choices, count)
                if count == 1 or not overlaps(group[0], group[1])
            ),
            key=lambda group: (
                sum(
                    (
                        abs(interval.start + (interval.end - interval.start) / 2 - center)
                        for interval, center in zip(group, centers, strict=True)
                    ),
                    timedelta(),
                ),
                tuple(interval.start for interval in group),
            ),
            default=None,
        )
        if best is not None:
            prepared = prepare_day(
                context, load_factor=factor, rest_intervals=(*rest_intervals, *best)
            )
            return prepared, missing - count
    return prepared, missing
