from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.modules.biorhythm.types import Cycle

ALGORITHM_VERSION: Final = "1.0.0"
CYCLES: Final = tuple(Cycle)
PERIODS: Final[Mapping[Cycle, int]] = MappingProxyType(
    {Cycle.PHYSICAL: 23, Cycle.EMOTIONAL: 28, Cycle.INTELLECTUAL: 33}
)
DAY_MICROSECONDS: Final = 86_400_000_000
NUMERICAL_TOLERANCE: Final = 1e-12
PHASE_THRESHOLD: Final = 0.5
PHASE_BOUNDARIES: Final = (-1.0, -PHASE_THRESHOLD, 0.0, PHASE_THRESHOLD, 1.0)
MAX_FORECAST_DAYS: Final = 62
