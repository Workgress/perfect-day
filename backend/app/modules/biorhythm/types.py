from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Cycle(StrEnum):
    PHYSICAL = "physical"
    EMOTIONAL = "emotional"
    INTELLECTUAL = "intellectual"


class Phase(StrEnum):
    PEAK = "peak"
    RISING = "rising"
    DECLINING = "declining"
    MINIMUM = "minimum"


class Trend(StrEnum):
    UP = "up"
    DOWN = "down"


class CriticalKind(StrEnum):
    NONE = "none"
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"


class Step(StrEnum):
    HOUR = "hour"
    DAY = "day"


class ForecastPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class CycleSnapshot:
    value: float
    percent: float
    phase: Phase
    trend: Trend


@dataclass(frozen=True)
class BioSnapshot:
    at: datetime
    cycles: dict[Cycle, CycleSnapshot]


@dataclass(frozen=True)
class CriticalCrossing:
    cycle: Cycle
    at: datetime


@dataclass(frozen=True)
class CriticalInfo:
    level: int
    kind: CriticalKind
    crossings: tuple[CriticalCrossing, ...]


@dataclass(frozen=True)
class ForecastPoint:
    at: datetime
    date: date
    cycles: dict[Cycle, CycleSnapshot]
    critical: CriticalInfo


@dataclass(frozen=True)
class Forecast:
    algorithm_version: str
    timezone: str
    start: date
    end: date
    step: Step
    points: tuple[ForecastPoint, ...]
    period: ForecastPeriod | None = None
