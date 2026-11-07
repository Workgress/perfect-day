from dataclasses import dataclass
from datetime import datetime
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
