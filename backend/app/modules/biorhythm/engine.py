from collections.abc import Sequence
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray

from app.core.time import local_day_bounds, to_utc
from app.modules.biorhythm.config import (
    CYCLES,
    DAY_MICROSECONDS,
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
    Phase,
    Trend,
)

type FloatArray = NDArray[np.float64]
type IntArray = NDArray[np.int64]
type Moments = Sequence[datetime] | NDArray[np.object_]


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
    cycles = {}
    for index, cycle in enumerate(CYCLES):
        value = float(values[index])
        cycles[cycle] = CycleSnapshot(
            value=value,
            percent=percent(value),
            phase=phase(value),
            trend=_trend(value, float(cosines[index])),
        )
    return BioSnapshot(at=to_utc(at_utc), cycles=cycles)


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
