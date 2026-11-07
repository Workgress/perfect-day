from calendar import monthrange
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

from app.core.time import LocalTimeError, local_day_bounds, local_time_candidates, to_utc
from app.modules.biorhythm.config import (
    ALGORITHM_VERSION,
    CYCLES,
    DAY_MICROSECONDS,
    MAX_FORECAST_DAYS,
    NUMERICAL_TOLERANCE,
    PERIODS,
    PHASE_BOUNDARIES,
    PHASE_THRESHOLD,
)
from app.modules.biorhythm.types import (
    BioSnapshot,
    CriticalCrossing,
    CriticalInfo,
    CriticalKind,
    Cycle,
    CycleSnapshot,
    Forecast,
    ForecastPeriod,
    ForecastPoint,
    ForecastRange,
    Phase,
    Step,
    Trend,
)

type FloatArray = NDArray[np.float64]
type IntArray = NDArray[np.int64]
type Moments = Sequence[datetime] | NDArray[np.object_]


class ForecastValidationError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


def _elapsed_microseconds(birth_utc: datetime, at: datetime) -> int:
    if not isinstance(at, datetime):
        raise ValueError("Моменты должны быть datetime с часовым поясом")
    elapsed = to_utc(at) - birth_utc
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _elapsed_array(birth_utc: datetime, moments: Moments) -> IntArray:
    birth_utc = to_utc(birth_utc)
    array = np.asarray(moments, dtype=object)
    if array.ndim != 1:
        raise ValueError("Массив моментов должен быть одномерным")
    return np.fromiter(
        (_elapsed_microseconds(birth_utc, moment) for moment in array),
        dtype=np.int64,
        count=array.size,
    )


def _angles(elapsed_us: IntArray, cycles: tuple[Cycle, ...]) -> FloatArray:
    periods_us = np.array([PERIODS[cycle] * DAY_MICROSECONDS for cycle in cycles], dtype=np.int64)
    # Integer modulo preserves exact periodicity and small offsets even for
    # dates centuries apart. Broadcasting produces a moments-by-cycles matrix.
    positions = elapsed_us[:, np.newaxis] % periods_us
    return (positions / periods_us) * (2 * np.pi)


def _normalize(values: FloatArray) -> FloatArray:
    normalized = np.clip(values, -1.0, 1.0)
    for boundary in PHASE_BOUNDARIES:
        normalized = np.where(
            np.abs(normalized - boundary) <= NUMERICAL_TOLERANCE, boundary, normalized
        )
    return normalized


def _validated_value(value: float) -> float:
    if not isfinite(value) or abs(value) > 1 + NUMERICAL_TOLERANCE:
        raise ValueError("Значение цикла должно быть конечным числом от -1 до 1")
    return float(_normalize(np.array([value], dtype=np.float64))[0])


def phase(value: float) -> Phase:
    """Classify the unrounded cycle value, with the shared boundary tolerance."""
    value = _validated_value(value)
    if value >= PHASE_THRESHOLD:
        return Phase.PEAK
    if value >= 0:
        return Phase.RISING
    if value > -PHASE_THRESHOLD:
        return Phase.DECLINING
    return Phase.MINIMUM


def percent(value: float) -> float:
    """One decimal place, ties to even; never return negative zero."""
    value = _validated_value(value)
    rounded = float(np.rint(value * 1000) / 10)
    return 0.0 if rounded == 0 else rounded


def _trend(value: float, cosine: float) -> Trend:
    if abs(cosine) <= NUMERICAL_TOLERANCE:
        return Trend.DOWN if value > 0 else Trend.UP
    return Trend.UP if cosine > 0 else Trend.DOWN


def _cycle_snapshots(values: FloatArray, cosines: FloatArray) -> dict[Cycle, CycleSnapshot]:
    cycles = {}
    for index, cycle in enumerate(CYCLES):
        value = float(values[index])
        cycles[cycle] = CycleSnapshot(
            value=value,
            percent=percent(value),
            phase=phase(value),
            trend=_trend(value, float(cosines[index])),
        )
    return cycles


def cycle_value(birth_utc: datetime, at_utc: datetime, cycle: Cycle) -> float:
    """Value of one cycle; negative elapsed time is valid in the pure engine."""
    cycle = Cycle(cycle)
    elapsed = _elapsed_array(birth_utc, [at_utc])
    return float(_normalize(np.sin(_angles(elapsed, (cycle,))))[0, 0])


def snapshot(birth_utc: datetime, at_utc: datetime) -> BioSnapshot:
    """Three cycles at one explicit instant, normalized to UTC."""
    elapsed = _elapsed_array(birth_utc, [at_utc])
    angles = _angles(elapsed, CYCLES)
    values = _normalize(np.sin(angles))[0]
    cosines = np.cos(angles)[0]
    return BioSnapshot(at=to_utc(at_utc), cycles=_cycle_snapshots(values, cosines))


def series(birth_utc: datetime, moments: Moments) -> dict[Cycle, FloatArray]:
    """Vectorized values for aware datetimes; preserve input order and repeats.

    NumPy inputs must be one-dimensional object arrays of aware datetimes.
    datetime64 has no timezone and is not accepted. An empty input returns
    three empty float64 arrays. Calendar grids are built outside this function.
    """
    elapsed = _elapsed_array(birth_utc, moments)
    values = _normalize(np.sin(_angles(elapsed, CYCLES)))
    return {cycle: values[:, index].copy() for index, cycle in enumerate(CYCLES)}


def critical_info(birth_utc: datetime, day: date, tz: ZoneInfo) -> CriticalInfo:
    """Analytical zero crossings in a local day, with exact UTC timestamps.

    The interval is [local midnight, next local midnight), including DST.
    The pure engine accepts negative cycle indices and the birth instant k=0.
    No sign sampling or floating-point tolerance is used to assign a day.
    """
    birth_utc = to_utc(birth_utc)
    start, end = local_day_bounds(day, tz)
    start_us = _elapsed_microseconds(birth_utc, start)
    end_us = _elapsed_microseconds(birth_utc, end)
    crossings = []
    for cycle in CYCLES:
        half_period_us = PERIODS[cycle] * DAY_MICROSECONDS // 2
        index = -(-start_us // half_period_us)  # ceil, including negative elapsed time
        offset_us = index * half_period_us
        # Each half-period is >= 11.5 days, longer than any supported local day:
        # only the first candidate per cycle can belong to this day.
        if offset_us < end_us:
            crossings.append(
                CriticalCrossing(cycle=cycle, at=birth_utc + timedelta(microseconds=offset_us))
            )
    crossings.sort(key=lambda crossing: (crossing.at, CYCLES.index(crossing.cycle)))
    level = len({crossing.cycle for crossing in crossings})
    return CriticalInfo(level=level, kind=tuple(CriticalKind)[level], crossings=tuple(crossings))


def _validate_forecast_range(start: date, days: int) -> None:
    if not isinstance(start, date) or isinstance(start, datetime):
        raise ForecastValidationError("start", "INVALID_DATE", "Укажите локальную дату без времени")
    if type(days) is not int or days < 1:
        raise ForecastValidationError(
            "days", "RANGE_INVALID", "Диапазон должен содержать хотя бы день"
        )
    if days > MAX_FORECAST_DAYS:
        raise ForecastValidationError("days", "RANGE_TOO_LONG", "Максимальный диапазон — 62 дня")
    try:
        start + timedelta(days=days)  # The exclusive end must also be representable.
    except OverflowError as exc:
        raise ForecastValidationError(
            "start", "DATE_RANGE_UNSUPPORTED", "Диапазон выходит за поддерживаемые даты"
        ) from exc


def time_grid(start: date, days: int, tz: ZoneInfo, step: Step = Step.DAY) -> tuple[datetime, ...]:
    """UTC instants for local dates, inclusive start, at most 62 days.

    Hourly grids restart at each day's first instant and advance in UTC.
    Daily points use local noon, choosing its earlier occurrence if repeated.
    """
    _validate_forecast_range(start, days)
    try:
        step = Step(step)
    except ValueError as exc:
        raise ForecastValidationError(
            "step", "INVALID_STEP", "Шаг должен быть hour или day"
        ) from exc
    moments = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        day_start, day_end = local_day_bounds(day, tz)
        if step is Step.DAY:
            candidates = local_time_candidates(datetime.combine(day, time(12)), tz)
            if not candidates:
                raise LocalTimeError(
                    "LOCAL_TIME_NONEXISTENT",
                    "Локальные 12:00 отсутствуют из-за смены часового пояса",
                )
            moments.append(candidates[0])
        else:
            at = day_start
            while at < day_end:
                moments.append(at)
                at += timedelta(hours=1)
    return tuple(moments)


def forecast(
    birth_utc: datetime, start: date, days: int, tz: ZoneInfo, step: Step = Step.DAY
) -> Forecast:
    """Vectorized cycles and daily criticality on an explicit calendar grid.

    Like the other pure functions this accepts moments before birth. The
    future API validates BEFORE_BIRTH without silently truncating the series.
    """
    birth_utc = to_utc(birth_utc)
    moments = time_grid(start, days, tz, step)
    angles = _angles(_elapsed_array(birth_utc, moments), CYCLES)
    values = _normalize(np.sin(angles))
    cosines = np.cos(angles)
    critical_by_day = {
        day: critical_info(birth_utc, day, tz)
        for day in (start + timedelta(days=offset) for offset in range(days))
    }
    points = []
    for index, at in enumerate(moments):
        day = at.astimezone(tz).date()
        points.append(
            ForecastPoint(
                at=at,
                date=day,
                cycles=_cycle_snapshots(values[index], cosines[index]),
                critical=critical_by_day[day],
            )
        )
    return Forecast(
        algorithm_version=ALGORITHM_VERSION,
        timezone=tz.key,
        start=start,
        end=start + timedelta(days=days - 1),
        step=Step(step),
        points=tuple(points),
    )


def forecast_range(at_utc: datetime, period: ForecastPeriod, tz: ZoneInfo) -> ForecastRange:
    """Resolve calendar parameters without calculating the cycle values."""
    try:
        period = ForecastPeriod(period)
    except ValueError as exc:
        raise ForecastValidationError(
            "period", "INVALID_PERIOD", "Период должен быть day, week или month"
        ) from exc
    start = to_utc(at_utc).astimezone(tz).date()
    if period is ForecastPeriod.DAY:
        days, step = 1, Step.HOUR
    elif period is ForecastPeriod.WEEK:
        days, step = 7, Step.DAY
    else:
        year, month = start.year + start.month // 12, start.month % 12 + 1
        try:
            end = start.replace(
                year=year, month=month, day=min(start.day, monthrange(year, month)[1])
            )
        except ValueError as exc:
            raise ForecastValidationError(
                "start", "DATE_RANGE_UNSUPPORTED", "Диапазон выходит за поддерживаемые даты"
            ) from exc
        days, step = (end - start).days, Step.DAY
    return ForecastRange(start=start, days=days, step=step, period=period)


def forecast_for_period(
    birth_utc: datetime, at_utc: datetime, period: ForecastPeriod, tz: ZoneInfo
) -> Forecast:
    """Day/week/rolling-month forecast anchored to an explicit instant."""
    params = forecast_range(at_utc, period, tz)
    return replace(
        forecast(birth_utc, params.start, params.days, tz, params.step), period=params.period
    )
