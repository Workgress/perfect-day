from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.modules.biorhythm.types import Cycle

ALGORITHM_VERSION: Final = "planner-1.0.0"
GRID_STEP_MINUTES: Final = 15
MIN_TASK_DURATION_MINUTES: Final = 5
MAX_TASK_DURATION_MINUTES: Final = 480

CHRONOTYPE_SHIFT_HOURS: Final[Mapping[str, int]] = MappingProxyType(
    {"lark": -1, "dove": 0, "owl": 3}
)
# The published 07–22 table tapers to zero at 06/23; the rest of the night is zero.
PROFILE_HOURS: Final[tuple[int, ...]] = (0, 6, *range(7, 23), 23, 24)
CIRCADIAN_PROFILES: Final[Mapping[Cycle, tuple[float, ...]]] = MappingProxyType(
    {
        Cycle.INTELLECTUAL: (
            0,
            0,
            0.40,
            0.60,
            0.80,
            1,
            1,
            0.85,
            0.60,
            0.50,
            0.65,
            0.80,
            0.75,
            0.60,
            0.50,
            0.40,
            0.30,
            0.20,
            0,
            0,
        ),
        Cycle.PHYSICAL: (
            0,
            0,
            0.40,
            0.50,
            0.55,
            0.60,
            0.65,
            0.65,
            0.55,
            0.60,
            0.85,
            1,
            1,
            0.90,
            0.70,
            0.50,
            0.35,
            0.25,
            0,
            0,
        ),
        Cycle.EMOTIONAL: (
            0,
            0,
            0.40,
            0.55,
            0.70,
            0.80,
            0.90,
            0.90,
            0.70,
            0.60,
            0.65,
            0.75,
            0.90,
            0.85,
            0.70,
            0.55,
            0.40,
            0.30,
            0,
            0,
        ),
    }
)
TASK_CYCLES: Final[Mapping[str, Cycle]] = MappingProxyType(
    {
        "intellectual": Cycle.INTELLECTUAL,
        "physical": Cycle.PHYSICAL,
        "creative": Cycle.EMOTIONAL,
    }
)
PEAK_WINDOW_THRESHOLD: Final = 0.8
PREFERRED_START_BONUS: Final = 0.3
PREFERRED_START_TOLERANCE_MINUTES: Final = 30

HIGH_INTENSITY_KINDS: Final = frozenset({"intellectual", "physical"})
HIGH_INTENSITY_CAP_MINUTES: Final = 240
INTENSITY_GAP_MINUTES: Final = 10
SHORT_BREAK_MINUTES: Final = 15
LONG_BREAK_MINUTES: Final = 30
CONTINUOUS_SHORT_LIMIT_MINUTES: Final = 90
CONTINUOUS_LONG_LIMIT_MINUTES: Final = 120
