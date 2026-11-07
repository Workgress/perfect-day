import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from math import copysign, sin, tau
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.biorhythm.config import ALGORITHM_VERSION, CYCLES, PERIODS
from app.modules.biorhythm.engine import cycle_value, percent, phase, series, snapshot
from app.modules.biorhythm.types import Cycle, Phase, Trend

BIRTH = datetime(2000, 1, 1, 12, tzinfo=UTC)


def test_algorithm_constants() -> None:
    assert ALGORITHM_VERSION == "1.0.0"
    assert dict(PERIODS) == {"physical": 23, "emotional": 28, "intellectual": 33}
    assert CYCLES == (Cycle.PHYSICAL, Cycle.EMOTIONAL, Cycle.INTELLECTUAL)


@pytest.mark.parametrize("cycle", CYCLES)
@pytest.mark.parametrize(
    ("fraction", "expected", "expected_phase", "expected_trend"),
    [
        (0, 0.0, Phase.RISING, Trend.UP),
        (0.25, 1.0, Phase.PEAK, Trend.DOWN),
        (0.5, 0.0, Phase.RISING, Trend.DOWN),
        (0.75, -1.0, Phase.MINIMUM, Trend.UP),
        (1.0, 0.0, Phase.RISING, Trend.UP),
        (-0.25, -1.0, Phase.MINIMUM, Trend.UP),
    ],
)
def test_exact_quarter_periods(
    cycle: Cycle, fraction: float, expected: float, expected_phase: Phase, expected_trend: Trend
) -> None:
    at = BIRTH + timedelta(days=PERIODS[cycle] * fraction)
    assert cycle_value(BIRTH, at, cycle) == expected
    state = snapshot(BIRTH, at).cycles[cycle]
    assert state.value == expected
    assert state.percent == expected * 100
    assert state.phase is expected_phase
    assert state.trend is expected_trend


@pytest.mark.parametrize("cycle", CYCLES)
def test_half_value_boundaries_are_exact(cycle: Cycle) -> None:
    for numerator, expected in [(1, 0.5), (5, 0.5), (7, -0.5), (11, -0.5)]:
        at = BIRTH + timedelta(seconds=PERIODS[cycle] * 86400 * numerator / 12)
        state = snapshot(BIRTH, at).cycles[cycle]
        assert state.value == expected
        assert state.phase is (Phase.PEAK if expected > 0 else Phase.MINIMUM)


@pytest.mark.parametrize("cycle", CYCLES)
@pytest.mark.parametrize("whole_periods", [-1000, 0, 1000])
def test_exact_extrema_survive_centuries(cycle: Cycle, whole_periods: int) -> None:
    at = BIRTH + timedelta(days=PERIODS[cycle] * whole_periods + PERIODS[cycle] / 4)
    assert cycle_value(BIRTH, at, cycle) == 1.0
    assert snapshot(BIRTH, at).cycles[cycle].trend is Trend.DOWN


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.0, Phase.MINIMUM),
        (-0.5, Phase.MINIMUM),
        (-0.499, Phase.DECLINING),
        (-0.1, Phase.DECLINING),
        (0.0, Phase.RISING),
        (0.1, Phase.RISING),
        (0.499, Phase.RISING),
        (0.5, Phase.PEAK),
        (1.0, Phase.PEAK),
        (-0.5 + 5e-13, Phase.MINIMUM),
        (-0.5 + 2e-12, Phase.DECLINING),
        (-5e-13, Phase.RISING),
        (-2e-12, Phase.DECLINING),
        (0.5 - 5e-13, Phase.PEAK),
        (0.5 - 2e-12, Phase.RISING),
        (1 + 5e-13, Phase.PEAK),
        (-1 - 5e-13, Phase.MINIMUM),
    ],
)
def test_phase_intervals_and_boundary_tolerance(value: float, expected: Phase) -> None:
    assert phase(value) is expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.01, -1.01])
def test_nonfinite_and_out_of_range_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="конечным числом"):
        phase(value)
    with pytest.raises(ValueError, match="конечным числом"):
        percent(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, 100.0),
        (-1.0, -100.0),
        (0.1235, 12.4),
        (0.1245, 12.4),
        (-0.1235, -12.4),
        (-0.1245, -12.4),
        (0.0005, 0.0),
        (0.0015, 0.2),
        (-0.0004, 0.0),
        (-0.0, 0.0),
    ],
)
def test_percent_rounding_is_half_even_without_negative_zero(value: float, expected: float) -> None:
    actual = percent(value)
    assert actual == expected
    if actual == 0:
        assert copysign(1, actual) == 1


def test_phase_is_not_based_on_rounded_percent() -> None:
    assert percent(0.49999) == 50.0
    assert phase(0.49999) is Phase.RISING
    assert percent(-0.49999) == -50.0
    assert phase(-0.49999) is Phase.DECLINING


@pytest.mark.parametrize(
    ("part", "expected_phase", "expected_trend"),
    [
        (1, Phase.RISING, Trend.UP),
        (11, Phase.RISING, Trend.DOWN),
        (13, Phase.DECLINING, Trend.DOWN),
        (23, Phase.DECLINING, Trend.UP),
    ],
)
def test_phase_and_direction_are_independent(
    part: int, expected_phase: Phase, expected_trend: Trend
) -> None:
    at = BIRTH + timedelta(hours=23 * part)
    state = snapshot(BIRTH, at).cycles[Cycle.PHYSICAL]
    assert state.phase is expected_phase
    assert state.trend is expected_trend


@pytest.mark.parametrize("cycle", CYCLES)
@pytest.mark.parametrize("days", [-10000.125, -1.5, 0.125, 1.0, 10000.125])
def test_values_match_independent_scalar_formula(cycle: Cycle, days: float) -> None:
    at = BIRTH + timedelta(days=days)
    expected = sin(tau * days / PERIODS[cycle])
    assert cycle_value(BIRTH, at, cycle) == pytest.approx(expected, abs=1e-12)


def test_snapshot_has_plain_values_and_utc_timestamp() -> None:
    at = datetime(2026, 11, 7, 15, 0, 0, 123456, tzinfo=timezone(timedelta(hours=5)))
    result = snapshot(BIRTH, at)
    assert result.at == datetime(2026, 11, 7, 10, 0, 0, 123456, tzinfo=UTC)
    assert result.at.tzinfo is UTC
    assert tuple(result.cycles) == CYCLES
    for cycle in result.cycles.values():
        assert type(cycle.value) is float
        assert type(cycle.percent) is float
    # Domain dataclasses are separate from HTTP schemas; cycle values already
    # use JSON-compatible types without NumPy scalar encoders.
    data = asdict(result)
    data["at"] = result.at.isoformat()
    assert json.loads(json.dumps(data))["cycles"]["physical"]["phase"] in set(Phase)
    assert result == snapshot(BIRTH, at)


def test_series_preserves_order_repeats_and_does_not_mutate_input() -> None:
    moments = np.array([BIRTH + timedelta(days=1), BIRTH, BIRTH + timedelta(days=1)], dtype=object)
    original = moments.copy()
    result = series(BIRTH, moments)
    np.testing.assert_array_equal(moments, original)
    assert tuple(result) == CYCLES
    for cycle in CYCLES:
        assert result[cycle].dtype == np.float64
        assert result[cycle].shape == (3,)
        assert result[cycle][0] == result[cycle][2]
        assert result[cycle][1] == 0
        for index, moment in enumerate(moments):
            assert result[cycle][index] == cycle_value(BIRTH, moment, cycle)


def test_empty_series_has_three_empty_float_arrays() -> None:
    result = series(BIRTH, [])
    assert tuple(result) == CYCLES
    for values in result.values():
        assert values.shape == (0,) and values.dtype == np.float64


@pytest.mark.parametrize(
    "moments",
    [
        np.array(BIRTH, dtype=object),
        np.array([[BIRTH]], dtype=object),
        np.empty((0, 3), dtype=object),
    ],
)
def test_series_rejects_non_one_dimensional_arrays(moments: Any) -> None:
    with pytest.raises(ValueError, match="одномерным"):
        series(BIRTH, moments)


@pytest.mark.parametrize(
    "moments",
    [
        [datetime(2026, 11, 7)],
        np.array(["2026-11-07"], dtype="datetime64[us]"),
        np.array(["2026-11-07"], dtype="datetime64[ns]"),
        np.array([1.0], dtype=object),
        np.array([None], dtype=object),
        np.array(["2026-11-07T10:00:00Z"], dtype=object),
    ],
)
def test_series_rejects_implicit_or_missing_timezones(moments: Any) -> None:
    with pytest.raises(ValueError):
        series(BIRTH, moments)


def test_naive_birth_or_target_is_rejected_in_all_entry_points() -> None:
    naive = datetime(2000, 1, 1)
    with pytest.raises(ValueError, match="часовой пояс"):
        cycle_value(naive, BIRTH, Cycle.PHYSICAL)
    with pytest.raises(ValueError, match="часовой пояс"):
        snapshot(BIRTH, naive)
    with pytest.raises(ValueError, match="часовой пояс"):
        series(naive, [])


def test_unknown_cycle_is_rejected() -> None:
    with pytest.raises(ValueError):
        cycle_value(BIRTH, BIRTH, cast(Cycle, "unknown"))


def test_dst_fold_is_elapsed_in_utc_not_wall_clock_time() -> None:
    tz = ZoneInfo("Europe/Berlin")
    birth = datetime(2026, 10, 25, 1, 30, tzinfo=tz)
    moments = [datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=fold) for fold in (0, 1)]
    result = series(birth, moments)
    for cycle in CYCLES:
        for index, hours in enumerate((1, 2)):
            expected = sin(tau * hours / (24 * PERIODS[cycle]))
            assert result[cycle][index] == pytest.approx(expected, abs=1e-14)


def test_subsecond_precision_is_preserved() -> None:
    at = BIRTH + timedelta(seconds=1, microseconds=123456)
    expected = sin(tau * 1.123456 / (86400 * 23))
    assert cycle_value(BIRTH, at, Cycle.PHYSICAL) == pytest.approx(expected, abs=1e-16)


def test_leap_day_counts_as_elapsed_day() -> None:
    birth = datetime(2024, 2, 28, 12, tzinfo=UTC)
    at = datetime(2024, 3, 1, 12, tzinfo=UTC)
    for cycle in CYCLES:
        expected = sin(tau * 2 / PERIODS[cycle])
        assert cycle_value(birth, at, cycle) == pytest.approx(expected, abs=1e-14)


def test_full_python_datetime_range_remains_finite() -> None:
    birth = datetime.min.replace(tzinfo=UTC)
    at = datetime.max.replace(tzinfo=UTC)
    values = series(birth, [at])
    for cycle in CYCLES:
        assert np.isfinite(values[cycle]).all()
        assert -1 <= values[cycle][0] <= 1


def test_large_vector_matches_single_values() -> None:
    moments = [BIRTH + timedelta(hours=hour) for hour in range(10000)]
    result = series(BIRTH, moments)
    for cycle in CYCLES:
        assert result[cycle].shape == (10000,)
        assert np.isfinite(result[cycle]).all()
        assert np.all((result[cycle] >= -1) & (result[cycle] <= 1))
        for index in (0, 1, 999, 5000, 9999):
            assert result[cycle][index] == cycle_value(BIRTH, moments[index], cycle)


@given(
    cycle=st.sampled_from(CYCLES),
    elapsed_us=st.integers(-(10**15), 10**15),
    periods=st.integers(-1000, 1000),
)
def test_property_periodicity(cycle: Cycle, elapsed_us: int, periods: int) -> None:
    at = BIRTH + timedelta(microseconds=elapsed_us)
    shifted = at + timedelta(days=PERIODS[cycle] * periods)
    assert cycle_value(BIRTH, at, cycle) == cycle_value(BIRTH, shifted, cycle)


@given(
    offsets=st.lists(st.integers(-(10**15), 10**15), max_size=40),
)
@settings(max_examples=100)
def test_property_vector_scalar_snapshot_parity_and_range(offsets: list[int]) -> None:
    moments = [BIRTH + timedelta(microseconds=offset) for offset in offsets]
    values = series(BIRTH, moments)
    for index, at in enumerate(moments):
        state = snapshot(BIRTH, at)
        for cycle in CYCLES:
            value = state.cycles[cycle].value
            assert -1 <= value <= 1
            assert -100 <= state.cycles[cycle].percent <= 100
            assert values[cycle][index] == value == cycle_value(BIRTH, at, cycle)
