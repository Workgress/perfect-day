from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from math import sin, tau
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.biorhythm.types import Cycle
from app.modules.planner.contracts import (
    Chronotype,
    Interval,
    PlanContext,
    PlanProfile,
    PlanTask,
    TaskKind,
    TaskRef,
)
from app.modules.planner.energy import circadian, preference_bonus, score_interval
from app.modules.planner.engine import PlannerTimeError, candidate_intervals, make_time_grid

DAY = date(2026, 11, 14)
BIRTH = datetime(2000, 1, 1, 12, tzinfo=UTC)


def profile() -> PlanProfile:
    return PlanProfile(BIRTH, "UTC", "dove", time.min, time(23), time(1))


def task(kind: TaskKind = "intellectual", duration: int = 15) -> PlanTask:
    return PlanTask(TaskRef(task_index=0), kind, duration, DAY)


def interval_at_midpoint(hour: int) -> Interval:
    midpoint = datetime.combine(DAY, time(hour), UTC)
    return Interval(
        midpoint - timedelta(minutes=7, seconds=30), midpoint + timedelta(minutes=7, seconds=30)
    )


@pytest.mark.parametrize(
    ("cycle", "hour", "expected"),
    [
        (Cycle.INTELLECTUAL, 7, 0.4),
        (Cycle.INTELLECTUAL, 9, 0.8),
        (Cycle.INTELLECTUAL, 10, 1),
        (Cycle.INTELLECTUAL, 11, 1),
        (Cycle.INTELLECTUAL, 14, 0.5),
        (Cycle.INTELLECTUAL, 22, 0.2),
        (Cycle.PHYSICAL, 8, 0.5),
        (Cycle.PHYSICAL, 15, 0.85),
        (Cycle.PHYSICAL, 16, 1),
        (Cycle.PHYSICAL, 17, 1),
        (Cycle.PHYSICAL, 22, 0.25),
        (Cycle.EMOTIONAL, 8, 0.55),
        (Cycle.EMOTIONAL, 11, 0.9),
        (Cycle.EMOTIONAL, 12, 0.9),
        (Cycle.EMOTIONAL, 17, 0.9),
        (Cycle.EMOTIONAL, 22, 0.3),
    ],
)
def test_curve_control_values_match_backend_plan(
    cycle: Cycle, hour: float, expected: float
) -> None:
    assert circadian(cycle, hour, "dove") == expected


@pytest.mark.parametrize(
    ("cycle", "hour", "expected"),
    [
        (Cycle.INTELLECTUAL, 8.5, 0.7),
        (Cycle.PHYSICAL, 15.5, 0.925),
        (Cycle.EMOTIONAL, 10.25, 0.825),
        (Cycle.INTELLECTUAL, 6.5, 0.2),
        (Cycle.INTELLECTUAL, 22.5, 0.1),
    ],
)
def test_interpolation_and_explicit_night_edges(cycle: Cycle, hour: float, expected: float) -> None:
    assert circadian(cycle, hour, "dove") == pytest.approx(expected, rel=0, abs=1e-14)


@pytest.mark.parametrize("hour", [0, 3, 6, 23, 24])
@pytest.mark.parametrize("cycle", list(Cycle))
def test_unshifted_night_is_zero(cycle: Cycle, hour: float) -> None:
    assert circadian(cycle, hour, "dove") == 0


@pytest.mark.parametrize(("chronotype", "hour"), [("lark", 9), ("dove", 10), ("owl", 13)])
def test_chronotype_shift_places_intellectual_peak(chronotype: Chronotype, hour: float) -> None:
    assert circadian(Cycle.INTELLECTUAL, hour, chronotype) == 1


def test_owl_curve_wraps_after_midnight_without_extrapolation() -> None:
    assert circadian(Cycle.INTELLECTUAL, 0, "owl") == 0.3
    assert circadian(Cycle.INTELLECTUAL, 1, "owl") == 0.2
    assert circadian(Cycle.INTELLECTUAL, 2, "owl") == 0


@pytest.mark.parametrize("hour", [float("nan"), float("inf"), -1, 24.01, True])
def test_invalid_wall_clock_hour_is_rejected(hour: Any) -> None:
    with pytest.raises(ValueError, match="local_hour"):
        circadian(Cycle.INTELLECTUAL, hour, "dove")


def test_unknown_curve_and_chronotype_are_rejected() -> None:
    with pytest.raises(ValueError):
        circadian("unknown", 10, "dove")
    with pytest.raises(ValueError, match="chronotype"):
        circadian(Cycle.INTELLECTUAL, 10, "unknown")


@pytest.mark.parametrize(
    ("kind", "cycle", "period", "hour", "curve"),
    [
        ("intellectual", Cycle.INTELLECTUAL, 33, 10, 1),
        ("physical", Cycle.PHYSICAL, 23, 16, 1),
        ("creative", Cycle.EMOTIONAL, 28, 11, 0.9),
    ],
)
@pytest.mark.parametrize(("fraction", "value"), [(0, 0), (0.25, 1), (0.5, 0), (0.75, -1)])
def test_rating_matches_hand_calculated_cycle_quarters(
    kind: TaskKind,
    cycle: Cycle,
    period: int,
    hour: int,
    curve: float,
    fraction: float,
    value: float,
) -> None:
    interval = interval_at_midpoint(hour)
    midpoint = datetime.combine(DAY, time(hour), UTC)
    params = replace(profile(), birth_utc=midpoint - timedelta(days=period * fraction))
    result = score_interval(params, task(kind), interval)
    assert result.cycle == cycle
    assert result.cycle_mean == value
    assert result.circadian_mean == curve
    assert result.base_score == pytest.approx(curve * (0.75 + 0.25 * value), rel=0, abs=1e-14)
    assert result.total == result.base_score
    assert result.peak_fraction == 1


def test_routine_prefers_low_energy_and_uses_all_three_cycles() -> None:
    interval = interval_at_midpoint(10)
    zero_cycles = replace(profile(), birth_utc=datetime.combine(DAY, time(10), UTC))
    rating = score_interval(zero_cycles, task("routine"), interval)
    # At 10:00 the three scores are .75, .45, .60; routine = 1 - .75.
    assert rating.base_score == 0.25
    assert rating.cycle is rating.cycle_mean is rating.circadian_mean is None
    assert rating.peak_fraction == 0
    assert score_interval(zero_cycles, task("routine"), interval_at_midpoint(3)).base_score == 1


def test_partial_segment_is_weighted_by_two_minutes_instead_of_fifteen() -> None:
    start = datetime.combine(DAY, time(9, 45), UTC)
    interval = Interval(start, start + timedelta(minutes=17))
    result = score_interval(profile(), task(duration=17), interval)
    first = start + timedelta(minutes=7, seconds=30)
    last = start + timedelta(minutes=16)

    def reference(at: datetime, curve: float) -> float:
        seconds = (at - BIRTH).total_seconds()
        value = sin(tau * ((seconds % (33 * 86400)) / (33 * 86400)))
        return curve * (0.75 + 0.25 * value)

    expected = (15 * reference(first, 0.975) + 2 * reference(last, 1)) / 17
    assert result.sample_count == 2
    assert result.base_score == pytest.approx(expected, rel=0, abs=1e-12)
    assert result.circadian_mean == pytest.approx((15 * 0.975 + 2) / 17, rel=0, abs=1e-14)


def test_long_interval_does_not_receive_only_its_midpoint_peak_score() -> None:
    interval = Interval(datetime.combine(DAY, time(9), UTC), datetime.combine(DAY, time(13), UTC))
    rating = score_interval(profile(), task(duration=240), interval)
    assert rating.sample_count == 16
    assert rating.circadian_mean == pytest.approx(0.8875, rel=0, abs=1e-14)
    assert rating.peak_fraction == 13 / 16
    assert rating.base_score < 0.95


def test_priority_does_not_change_the_rating_of_the_same_interval() -> None:
    interval = interval_at_midpoint(10)
    assert score_interval(profile(), task(), interval) == score_interval(
        profile(), replace(task(), priority="high"), interval
    )


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(minutes=-30), 0.3),
        (timedelta(minutes=30), 0.3),
        (timedelta(minutes=-30, microseconds=-1), 0),
        (timedelta(minutes=30, microseconds=1), 0),
    ],
)
def test_preferred_start_has_inclusive_thirty_minute_boundary(
    offset: timedelta, expected: float
) -> None:
    preferred = datetime.combine(DAY, time(10), UTC)
    interval = Interval(preferred + offset, preferred + offset + timedelta(minutes=15))
    assert (
        preference_bonus(profile(), replace(task(), preferred_start=time(10)), interval) == expected
    )


def test_preference_bonus_is_not_clamped_to_one() -> None:
    interval = interval_at_midpoint(10)
    params = replace(
        profile(), birth_utc=datetime.combine(DAY, time(10), UTC) - timedelta(days=33 / 4)
    )
    rating = score_interval(params, replace(task(), preferred_start=time(9, 52, 30)), interval)
    assert rating.base_score == 1 and rating.preference_bonus == 0.3
    assert rating.total == 1.3


@pytest.mark.parametrize(
    ("day", "code"),
    [(date(2026, 3, 29), "LOCAL_TIME_NONEXISTENT"), (date(2026, 10, 25), "LOCAL_TIME_AMBIGUOUS")],
)
def test_preferred_start_does_not_guess_a_dst_fold_or_missing_hour(day: date, code: str) -> None:
    planned = replace(task(), planned_date=day, preferred_start=time(2, 30))
    interval = Interval(
        datetime.combine(day, time(12), UTC), datetime.combine(day, time(12, 15), UTC)
    )
    with pytest.raises(PlannerTimeError) as error:
        preference_bonus(replace(profile(), timezone="Europe/Berlin"), planned, interval)
    assert (error.value.field, error.value.code) == ("preferred_start", code)


def test_preferred_start_uses_elapsed_distance_across_dst() -> None:
    day = date(2026, 3, 29)
    tz = ZoneInfo("Europe/Berlin")
    at = datetime.combine(day, time(1, 45), tz).astimezone(UTC)
    interval = Interval(at, at + timedelta(minutes=15))
    planned = replace(task(), planned_date=day, preferred_start=time(3))
    assert preference_bonus(replace(profile(), timezone=tz.key), planned, interval) == 0.3


def test_preferred_start_overflow_has_a_field_aware_domain_error() -> None:
    planned = replace(task(), planned_date=date.min, preferred_start=time.min)
    at = datetime(1, 1, 1, 3, tzinfo=UTC)
    with pytest.raises(PlannerTimeError) as error:
        preference_bonus(
            replace(profile(), timezone="Asia/Tokyo"),
            planned,
            Interval(at, at + timedelta(minutes=15)),
        )
    assert (error.value.field, error.value.code) == ("preferred_start", "DATE_RANGE_UNSUPPORTED")


def test_timezone_changes_daily_energy_without_shifting_computational_birth() -> None:
    at = datetime.combine(DAY, time(4, 52, 30), UTC)
    interval = Interval(at, at + timedelta(minutes=15))
    utc = score_interval(profile(), task(), interval)
    local = score_interval(replace(profile(), timezone="Asia/Yekaterinburg"), task(), interval)
    assert utc.circadian_mean == 0 and local.circadian_mean == 1
    assert utc.cycle_mean == local.cycle_mean
    assert utc.base_score == 0 < local.base_score


def test_interval_duration_and_local_date_must_match_the_task() -> None:
    interval = interval_at_midpoint(10)
    with pytest.raises(ValueError, match="duration"):
        score_interval(profile(), task(duration=17), interval)
    with pytest.raises(ValueError, match="planned date"):
        score_interval(profile(), replace(task(), planned_date=DAY + timedelta(days=1)), interval)
    start = datetime.combine(DAY, time(23, 50), UTC)
    with pytest.raises(ValueError, match="planned date"):
        score_interval(profile(), task(), Interval(start, start + timedelta(minutes=15)))


def test_last_partial_sample_at_datetime_max_does_not_overflow() -> None:
    start = datetime(9999, 12, 31, 23, 40, tzinfo=UTC)
    planned = replace(task("routine", 17), planned_date=date.max)
    rating = score_interval(profile(), planned, Interval(start, start + timedelta(minutes=17)))
    assert rating.sample_count == 2 and rating.base_score == 1


@pytest.mark.parametrize("kind", ["intellectual", "physical", "creative"])
@pytest.mark.parametrize(("chronotype", "shift"), [("lark", -1), ("dove", 0), ("owl", 3)])
def test_stages_one_to_three_rank_real_candidates_in_the_expected_chronotype_window(
    kind: TaskKind, chronotype: Chronotype, shift: int
) -> None:
    hours = {"intellectual": 10, "physical": 16, "creative": 11}
    periods = {"intellectual": 33, "physical": 23, "creative": 28}
    peak = datetime.combine(DAY, time(hours[kind], 30), UTC)
    params = replace(
        profile(), chronotype=chronotype, birth_utc=peak - timedelta(days=periods[kind] / 4)
    )
    planned = task(kind, 60)
    ctx = PlanContext(params, DAY, datetime(1900, 1, 1, tzinfo=UTC), (planned,), "preview")
    candidates = candidate_intervals(make_time_grid(ctx), planned.duration_min)
    best = max(candidates, key=lambda interval: score_interval(params, planned, interval).total)
    assert best.start.hour == hours[kind] + shift and best.start.minute == 0


@given(
    cycle=st.sampled_from(list(Cycle)),
    hour=st.floats(0, 24, allow_nan=False, allow_infinity=False),
    chronotype=st.sampled_from(["lark", "dove", "owl"]),
)
def test_property_daily_energy_is_bounded_and_shifts_the_base_curve(
    cycle: Cycle, hour: float, chronotype: Chronotype
) -> None:
    shifts = {"lark": -1, "dove": 0, "owl": 3}
    actual = circadian(cycle, hour, chronotype)
    assert 0 <= actual <= 1
    assert actual == circadian(cycle, (hour - shifts[chronotype]) % 24, "dove")


@given(
    duration=st.integers(5, 480),
    kind=st.sampled_from(["intellectual", "physical", "creative", "routine"]),
)
def test_property_rating_is_finite_bounded_and_deterministic(duration: int, kind: TaskKind) -> None:
    start = datetime.combine(DAY, time(8), UTC)
    interval = Interval(start, start + timedelta(minutes=duration))
    planned = task(kind, duration)
    result = score_interval(profile(), planned, interval)
    assert result == score_interval(profile(), planned, interval)
    assert 0 <= result.base_score <= 1
    assert 0 <= result.peak_fraction <= 1
    assert result.sample_count == (duration + 14) // 15
