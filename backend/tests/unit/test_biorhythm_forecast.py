from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.time import LocalTimeError, local_day_bounds, local_time_candidates
from app.modules.biorhythm.config import ALGORITHM_VERSION, CYCLES
from app.modules.biorhythm.engine import (
    ForecastValidationError,
    critical_info,
    forecast,
    forecast_for_period,
    series,
    snapshot,
    time_grid,
)
from app.modules.biorhythm.types import CriticalKind, Cycle, ForecastPeriod, Step, Trend

BIRTH = datetime(2000, 1, 1, tzinfo=UTC)
UTC_ZONE = ZoneInfo("UTC")


@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Moscow", "Europe/Berlin"])
def test_daily_grid_uses_local_noon_and_includes_both_dates(zone: str) -> None:
    tz = ZoneInfo(zone)
    start = date(2026, 11, 7)
    moments = time_grid(start, 3, tz)
    assert len(moments) == 3
    for index, moment in enumerate(moments):
        local = moment.astimezone(tz)
        assert local.date() == start + timedelta(days=index)
        assert (local.hour, local.minute, local.second) == (12, 0, 0)
        assert moment.tzinfo is UTC


@pytest.mark.parametrize(
    ("zone", "day", "count"),
    [
        ("UTC", date(2026, 11, 7), 24),
        ("Asia/Yekaterinburg", date(2026, 11, 7), 24),
        ("Europe/Berlin", date(2026, 3, 29), 23),
        ("Europe/Berlin", date(2026, 10, 25), 25),
        ("America/New_York", date(2026, 3, 8), 23),
        ("America/New_York", date(2026, 11, 1), 25),
        ("Australia/Lord_Howe", date(2026, 4, 5), 25),
        ("Australia/Lord_Howe", date(2026, 10, 4), 24),
        ("America/Sao_Paulo", date(2018, 11, 4), 23),
        ("America/Havana", date(2020, 11, 1), 25),
        ("Pacific/Kwajalein", date(1969, 9, 30), 47),
    ],
)
def test_hourly_grid_follows_actual_day_length(zone: str, day: date, count: int) -> None:
    tz = ZoneInfo(zone)
    moments = time_grid(day, 1, tz, Step.HOUR)
    start, end = local_day_bounds(day, tz)
    assert len(moments) == count
    assert moments[0] == start
    assert all(moment.tzinfo is UTC and start <= moment < end for moment in moments)
    assert all(moment.astimezone(tz).date() == day for moment in moments)
    assert all(right - left == timedelta(hours=1) for left, right in pairwise(moments))
    assert moments == tuple(sorted(set(moments)))


def test_repeated_hour_has_distinct_offsets_and_folds() -> None:
    tz = ZoneInfo("Europe/Berlin")
    moments = time_grid(date(2026, 10, 25), 1, tz, Step.HOUR)
    repeated = [moment.astimezone(tz) for moment in moments if moment.astimezone(tz).hour == 2]
    assert len(repeated) == 2
    assert [moment.fold for moment in repeated] == [0, 1]
    assert repeated[0].utcoffset() != repeated[1].utcoffset()
    assert repeated[1].astimezone(UTC) - repeated[0].astimezone(UTC) == timedelta(hours=1)


def test_hourly_grid_is_restarted_after_a_fractional_dst_day() -> None:
    tz = ZoneInfo("Australia/Lord_Howe")
    first = time_grid(date(2026, 10, 4), 1, tz, Step.HOUR)
    second = time_grid(date(2026, 10, 5), 1, tz, Step.HOUR)
    combined = time_grid(date(2026, 10, 4), 2, tz, Step.HOUR)
    assert combined == first + second
    assert second[0] - first[-1] == timedelta(minutes=30)


def test_daily_grid_uses_earlier_repeated_noon() -> None:
    tz = ZoneInfo("Pacific/Kwajalein")
    candidates = local_time_candidates(datetime(1969, 9, 30, 12), tz)
    assert len(candidates) == 2
    assert time_grid(date(1969, 9, 30), 1, tz) == (candidates[0],)


def test_daily_grid_rejects_missing_noon_without_silently_moving_point() -> None:
    tz = ZoneInfo("Africa/Khartoum")
    day = date(2000, 1, 15)
    with pytest.raises(LocalTimeError) as error:
        time_grid(day, 1, tz)
    assert error.value.code == "LOCAL_TIME_NONEXISTENT"
    hourly = time_grid(day, 1, tz, Step.HOUR)
    assert len(hourly) == 23
    assert all(moment.astimezone(tz).hour != 12 for moment in hourly)


@pytest.mark.parametrize("step", list(Step))
def test_skipped_date_inside_range_is_rejected(step: Step) -> None:
    with pytest.raises(LocalTimeError) as error:
        forecast(BIRTH, date(2011, 12, 29), 3, ZoneInfo("Pacific/Apia"), step)
    assert error.value.code == "LOCAL_DATE_NONEXISTENT"


@pytest.mark.parametrize("days", [0, -1, True, 1.5])
def test_invalid_range_length(days: int) -> None:
    with pytest.raises(ForecastValidationError) as error:
        time_grid(date(2026, 11, 7), days, UTC_ZONE)
    assert error.value.field == "days"
    assert error.value.code == "RANGE_INVALID"


def test_range_limit_is_inclusive_62_days() -> None:
    moments = time_grid(date(2026, 1, 1), 62, UTC_ZONE)
    assert len(moments) == 62
    assert moments[-1].date() == date(2026, 3, 3)
    with pytest.raises(ForecastValidationError) as error:
        time_grid(date(2026, 1, 1), 63, UTC_ZONE)
    assert error.value.code == "RANGE_TOO_LONG"


@pytest.mark.parametrize("start", [datetime(2026, 11, 7), "2026-11-07"])
def test_grid_requires_date_not_datetime_or_string(start: date) -> None:
    with pytest.raises(ForecastValidationError) as error:
        time_grid(start, 1, UTC_ZONE)
    assert error.value.code == "INVALID_DATE"


def test_exclusive_end_beyond_datetime_range_is_rejected() -> None:
    with pytest.raises(ForecastValidationError) as error:
        time_grid(date.max, 1, UTC_ZONE)
    assert error.value.code == "DATE_RANGE_UNSUPPORTED"


def test_invalid_step_is_rejected() -> None:
    with pytest.raises(ForecastValidationError) as error:
        time_grid(date(2026, 11, 7), 1, UTC_ZONE, cast(Step, "minute"))
    assert error.value.field == "step" and error.value.code == "INVALID_STEP"


@pytest.mark.parametrize("step", list(Step))
def test_forecast_points_match_snapshot_series_and_criticality(step: Step) -> None:
    tz = ZoneInfo("Europe/Berlin")
    result = forecast(BIRTH, date(2026, 10, 24), 3, tz, step)
    assert result.algorithm_version == ALGORITHM_VERSION
    assert result.timezone == "Europe/Berlin"
    assert result.start == date(2026, 10, 24) and result.end == date(2026, 10, 26)
    assert result.step is step and result.period is None
    assert len(result.points) == (73 if step is Step.HOUR else 3)
    moments = [point.at for point in result.points]
    values = series(BIRTH, moments)
    for index, point in enumerate(result.points):
        assert point.date == point.at.astimezone(tz).date()
        assert point.cycles == snapshot(BIRTH, point.at).cycles
        assert point.critical == critical_info(BIRTH, point.date, tz)
        for cycle in CYCLES:
            assert point.cycles[cycle].value == values[cycle][index]
    assert result == forecast(BIRTH, date(2026, 10, 24), 3, tz, step)


def test_daily_criticality_applies_to_hours_before_and_after_crossing() -> None:
    result = forecast(BIRTH, date(2000, 1, 12), 1, UTC_ZONE, Step.HOUR)
    crossing = datetime(2000, 1, 12, 12, tzinfo=UTC)
    for point in result.points:
        assert point.critical.kind is CriticalKind.SINGLE
        assert point.critical.crossings[0].at == crossing
    assert result.points[12].cycles[Cycle.PHYSICAL].value == 0
    assert result.points[12].cycles[Cycle.PHYSICAL].trend is Trend.DOWN


def test_forecast_at_exact_peak_retains_extremum_direction() -> None:
    result = forecast(BIRTH, date(2000, 1, 6), 1, UTC_ZONE, Step.HOUR)
    state = result.points[18].cycles[Cycle.PHYSICAL]
    assert state.value == 1 and state.percent == 100
    assert state.trend is Trend.DOWN


def test_pure_forecast_allows_points_before_birth() -> None:
    result = forecast(BIRTH, date(1999, 12, 31), 1, UTC_ZONE)
    assert result.points[0].at < BIRTH
    assert result.points[0].cycles == snapshot(BIRTH, result.points[0].at).cycles


def test_maximum_hourly_forecast_includes_extra_dst_hour() -> None:
    tz = ZoneInfo("America/New_York")
    result = forecast(BIRTH, date(2026, 10, 1), 62, tz, Step.HOUR)
    assert result.end == date(2026, 12, 1)
    assert len(result.points) == 62 * 24 + 1
    for index in (0, 100, 1000, len(result.points) - 1):
        point = result.points[index]
        assert point.cycles == snapshot(BIRTH, point.at).cycles
        assert point.critical == critical_info(BIRTH, point.date, tz)


def test_naive_birth_and_forecast_anchor_are_rejected() -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        forecast(datetime(2000, 1, 1), date(2026, 11, 7), 1, UTC_ZONE)
    with pytest.raises(ValueError, match="часовой пояс"):
        forecast_for_period(BIRTH, datetime(2026, 11, 7), ForecastPeriod.WEEK, UTC_ZONE)


@pytest.mark.parametrize(
    ("period", "count", "end", "step"),
    [
        (ForecastPeriod.DAY, 24, date(2026, 11, 7), Step.HOUR),
        (ForecastPeriod.WEEK, 7, date(2026, 11, 13), Step.DAY),
        (ForecastPeriod.MONTH, 30, date(2026, 12, 6), Step.DAY),
    ],
)
def test_period_forecast_matches_contract(
    period: ForecastPeriod, count: int, end: date, step: Step
) -> None:
    at = datetime(2026, 11, 7, 10, tzinfo=UTC)
    result = forecast_for_period(BIRTH, at, period, UTC_ZONE)
    assert result.start == date(2026, 11, 7) and result.end == end
    assert len(result.points) == count and result.step is step
    assert result.period is period


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        (date(2027, 1, 31), date(2027, 2, 27), 28),
        (date(2024, 1, 31), date(2024, 2, 28), 29),
        (date(2024, 2, 29), date(2024, 3, 28), 29),
        (date(2026, 2, 28), date(2026, 3, 27), 28),
        (date(2026, 3, 31), date(2026, 4, 29), 30),
        (date(2026, 12, 31), date(2027, 1, 30), 31),
    ],
)
def test_rolling_month_clamps_day_and_handles_leap_year(start: date, end: date, days: int) -> None:
    at = datetime.combine(start, datetime.min.time(), UTC)
    result = forecast_for_period(BIRTH, at, ForecastPeriod.MONTH, UTC_ZONE)
    assert result.start == start and result.end == end
    assert len(result.points) == days


def test_period_forecast_uses_local_date_not_utc_date() -> None:
    at = datetime(2026, 11, 7, 23, 30, tzinfo=UTC)
    tz = ZoneInfo("Asia/Yekaterinburg")
    result = forecast_for_period(BIRTH, at, ForecastPeriod.WEEK, tz)
    assert result.start == date(2026, 11, 8) and result.end == date(2026, 11, 14)
    assert result.points[0].at == datetime(2026, 11, 8, 7, tzinfo=UTC)
    assert result == forecast_for_period(BIRTH, at.astimezone(tz), ForecastPeriod.WEEK, tz)


def test_day_forecast_on_dst_transition_uses_23_hours() -> None:
    at = datetime(2026, 3, 29, 10, tzinfo=UTC)
    result = forecast_for_period(BIRTH, at, ForecastPeriod.DAY, ZoneInfo("Europe/Berlin"))
    assert len(result.points) == 23


def test_unrepresentable_rolling_month_is_rejected() -> None:
    with pytest.raises(ForecastValidationError) as error:
        forecast_for_period(
            BIRTH, datetime(9999, 12, 1, tzinfo=UTC), ForecastPeriod.MONTH, UTC_ZONE
        )
    assert error.value.code == "DATE_RANGE_UNSUPPORTED"


def test_invalid_period_is_rejected() -> None:
    with pytest.raises(ForecastValidationError) as error:
        forecast_for_period(
            BIRTH, datetime(2026, 11, 7, tzinfo=UTC), cast(ForecastPeriod, "year"), UTC_ZONE
        )
    assert error.value.field == "period" and error.value.code == "INVALID_PERIOD"


@given(
    start=st.dates(min_value=date(2001, 1, 1), max_value=date(2030, 12, 1)),
    days=st.integers(1, 5),
    zone=st.sampled_from(["UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"]),
    step=st.sampled_from(list(Step)),
)
@settings(max_examples=60)
def test_property_grid_dates_order_and_snapshot_parity(
    start: date, days: int, zone: str, step: Step
) -> None:
    tz = ZoneInfo(zone)
    result = forecast(BIRTH, start, days, tz, step)
    moments = tuple(point.at for point in result.points)
    assert moments == tuple(sorted(set(moments)))
    assert {point.date for point in result.points} == {
        start + timedelta(days=offset) for offset in range(days)
    }
    for point in result.points:
        assert point.date == point.at.astimezone(tz).date()
        assert point.cycles == snapshot(BIRTH, point.at).cycles
        assert point.critical == critical_info(BIRTH, point.date, tz)
