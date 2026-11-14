from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.biorhythm.config import ALGORITHM_VERSION as BIO_VERSION
from app.modules.planner.config import ALGORITHM_VERSION, GRID_STEP_MINUTES
from app.modules.planner.contracts import PlanContext, PlanMode, PlanProfile
from app.modules.planner.engine import (
    PlannerTimeError,
    candidate_intervals,
    deadline_boundary,
    make_time_grid,
)

DAY = date(2026, 11, 14)


def context(
    *,
    day: date = DAY,
    zone: str = "UTC",
    start: time = time(8),
    end: time = time(18),
    now: datetime = datetime(1900, 1, 1, tzinfo=UTC),
    mode: PlanMode = "replan",
) -> PlanContext:
    profile = PlanProfile(
        birth_utc=datetime(1900, 1, 1, tzinfo=UTC),
        timezone=zone,
        chronotype="dove",
        work_start=start,
        work_end=end,
        sleep_time=time(1),
    )
    return PlanContext(profile, day, now, (), mode)


def test_planner_configuration_does_not_change_biorhythm_version() -> None:
    assert ALGORITHM_VERSION == "planner-1.0.0"
    assert BIO_VERSION == "1.0.0"
    assert GRID_STEP_MINUTES == 15


@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"])
def test_work_window_and_grid_are_utc_instants_for_the_requested_local_day(zone: str) -> None:
    grid = make_time_grid(context(zone=zone))
    tz = ZoneInfo(zone)
    expected_start = datetime.combine(DAY, time(8), tz).astimezone(UTC)
    expected_end = datetime.combine(DAY, time(18), tz).astimezone(UTC)
    assert (grid.work_window.start, grid.work_window.end) == (expected_start, expected_end)
    assert grid.available_window == grid.work_window
    assert len(grid.starts) == 40
    assert grid.starts[0] == expected_start
    assert grid.starts[-1] == expected_end - timedelta(minutes=15)
    assert all(at.tzinfo is UTC and at.astimezone(tz).date() == DAY for at in grid.starts)
    assert all(right - left == timedelta(minutes=15) for left, right in pairwise(grid.starts))


def test_grid_anchor_is_work_start_not_a_rounded_wall_clock() -> None:
    grid = make_time_grid(context(start=time(8, 7), end=time(9)))
    assert [at.time() for at in grid.starts] == [time(8, 7), time(8, 22), time(8, 37), time(8, 52)]
    intervals = candidate_intervals(grid, 17)
    assert [(item.start.time(), item.end.time()) for item in intervals] == [
        (time(8, 7), time(8, 24)),
        (time(8, 22), time(8, 39)),
        (time(8, 37), time(8, 54)),
    ]
    assert all(item.end - item.start == timedelta(minutes=17) for item in intervals)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (time(7), time(8)),
        (time(8), time(8)),
        (time(8, 15), time(8, 15)),
        (time(8, 15, 0, 1), time(8, 30)),
        (time(8, 15, 59), time(8, 30)),
        (time(8, 59), None),
        (time(9), None),
        (time(10), None),
    ],
)
def test_current_time_never_rounds_down_to_a_past_start(now: time, expected: time | None) -> None:
    instant = datetime.combine(DAY, now, UTC)
    grid = make_time_grid(context(end=time(9), now=instant))
    assert (grid.starts[0].time() if grid.starts else None) == expected
    assert all(at >= instant for at in grid.starts)
    if instant < grid.work_window.end:
        assert grid.available_window is not None
        assert grid.available_window.start == max(grid.work_window.start, instant)
    else:
        assert grid.available_window is None


def test_rounding_up_preserves_nonstandard_work_anchor() -> None:
    grid = make_time_grid(
        context(start=time(8, 7), end=time(9), now=datetime.combine(DAY, time(8, 8), UTC))
    )
    assert grid.starts[0].time() == time(8, 22)


def test_now_uses_profile_timezone_instead_of_utc_calendar_date() -> None:
    before_work = datetime(2026, 11, 13, 23, tzinfo=UTC)
    grid = make_time_grid(context(zone="Asia/Yekaterinburg", now=before_work))
    assert grid.starts[0] == datetime(2026, 11, 14, 3, tzinfo=UTC)
    ended = make_time_grid(
        context(zone="America/New_York", now=datetime(2026, 11, 15, 1, tzinfo=UTC))
    )
    assert ended.available_window is None and ended.starts == ()


def test_past_day_has_no_new_candidates_and_future_day_has_full_window() -> None:
    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    past = make_time_grid(context(day=DAY - timedelta(days=1), now=now))
    future = make_time_grid(context(day=DAY + timedelta(days=1), now=now))
    assert past.available_window is None and candidate_intervals(past, 17) == ()
    assert future.available_window == future.work_window and len(future.starts) == 40


def test_explicit_weekend_and_early_window_are_not_cut_by_hidden_profile_defaults() -> None:
    grid = make_time_grid(context(start=time(4), end=time(10), mode="preview"))
    assert DAY.isoweekday() == 6
    assert grid.starts[0].time() == time(4)
    assert len(grid.starts) == 24


@pytest.mark.parametrize("duration", [5, 17, 60, 480])
def test_candidate_intervals_preserve_duration_and_include_exact_work_end(duration: int) -> None:
    grid = make_time_grid(context())
    intervals = candidate_intervals(grid, duration)
    assert intervals
    assert all(item.end - item.start == timedelta(minutes=duration) for item in intervals)
    assert all(
        grid.work_window.start <= item.start < item.end <= grid.work_window.end
        for item in intervals
    )
    if duration % 15 == 0:
        assert intervals[-1].end == grid.work_window.end


@pytest.mark.parametrize("duration", [True, 4, 481, 17.5, "17"])
def test_invalid_duration_is_not_coerced(duration: Any) -> None:
    with pytest.raises(ValueError, match="duration_min"):
        candidate_intervals(make_time_grid(context()), duration)


def test_too_short_remaining_window_returns_no_interval() -> None:
    grid = make_time_grid(context(start=time(8), end=time(8, 16)))
    assert candidate_intervals(grid, 17) == ()


@pytest.mark.parametrize(
    ("zone", "day", "hours", "count"),
    [
        ("Europe/Berlin", date(2026, 3, 29), 3, 12),
        ("Europe/Berlin", date(2026, 10, 25), 5, 20),
        ("America/New_York", date(2026, 3, 8), 3, 12),
        ("America/New_York", date(2026, 11, 1), 5, 20),
        ("Australia/Lord_Howe", date(2026, 4, 5), 4.5, 18),
        ("Australia/Lord_Howe", date(2026, 10, 4), 3.5, 14),
    ],
)
def test_grid_follows_actual_elapsed_time_across_dst(
    zone: str, day: date, hours: float, count: int
) -> None:
    grid = make_time_grid(context(day=day, zone=zone, start=time.min, end=time(4)))
    assert grid.work_window.end - grid.work_window.start == timedelta(hours=hours)
    assert len(grid.starts) == count
    assert grid.starts == tuple(sorted(set(grid.starts)))
    assert all(right - left == timedelta(minutes=15) for left, right in pairwise(grid.starts))
    assert all(at.astimezone(ZoneInfo(zone)).date() == day for at in grid.starts)


def test_repeated_hour_has_two_distinct_utc_starts() -> None:
    zone = "Europe/Berlin"
    grid = make_time_grid(context(day=date(2026, 10, 25), zone=zone, start=time.min, end=time(4)))
    repeated = [at for at in grid.starts if at.astimezone(ZoneInfo(zone)).time() == time(2, 30)]
    assert len(repeated) == 2
    assert repeated[1] - repeated[0] == timedelta(hours=1)
    assert [at.astimezone(ZoneInfo(zone)).fold for at in repeated] == [0, 1]


def test_preview_excludes_ambiguous_starts_and_ends_without_discarding_the_whole_day() -> None:
    ctx = context(day=date(2026, 10, 25), zone="Europe/Berlin", start=time.min, end=time(4))
    replan = make_time_grid(ctx)
    preview = make_time_grid(replace(ctx, mode="preview"))
    assert len(candidate_intervals(replan, 5)) == 20
    assert len(candidate_intervals(preview, 5)) == 12
    tz = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 10, 25, 1, 45, tzinfo=tz).astimezone(UTC)
    assert any(item.start == start for item in candidate_intervals(replan, 15))
    assert not any(item.start == start for item in candidate_intervals(preview, 15))
    # Both endpoints are unique, although the elapsed time crosses the rollback.
    assert any(item.start == start for item in candidate_intervals(preview, 150))


def test_preview_interval_crosses_spring_gap_using_elapsed_duration() -> None:
    ctx = context(
        day=date(2026, 3, 29), zone="Europe/Berlin", start=time.min, end=time(4), mode="preview"
    )
    tz = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 3, 29, 1, 45, tzinfo=tz).astimezone(UTC)
    interval = next(
        item for item in candidate_intervals(make_time_grid(ctx), 15) if item.start == start
    )
    assert interval.end.astimezone(tz).time() == time(3)
    assert interval.end - interval.start == timedelta(minutes=15)


@pytest.mark.parametrize(
    ("day", "start", "end", "field", "code"),
    [
        (date(2026, 3, 29), time(2, 30), time(4), "work_start", "LOCAL_TIME_NONEXISTENT"),
        (date(2026, 3, 29), time(1), time(2, 30), "work_end", "LOCAL_TIME_NONEXISTENT"),
        (date(2026, 10, 25), time(2, 30), time(4), "work_start", "LOCAL_TIME_AMBIGUOUS"),
        (date(2026, 10, 25), time(1), time(2, 30), "work_end", "LOCAL_TIME_AMBIGUOUS"),
    ],
)
def test_ambiguous_or_nonexistent_work_boundary_is_not_guessed(
    day: date, start: time, end: time, field: str, code: str
) -> None:
    with pytest.raises(PlannerTimeError) as error:
        make_time_grid(context(day=day, zone="Europe/Berlin", start=start, end=end))
    assert (error.value.field, error.value.code) == (field, code)


@pytest.mark.parametrize(
    ("day", "zone", "code"),
    [
        (date(2011, 12, 30), "Pacific/Apia", "LOCAL_DATE_NONEXISTENT"),
        (date.max, "UTC", "DATE_RANGE_UNSUPPORTED"),
        (date.min, "Asia/Tokyo", "DATE_RANGE_UNSUPPORTED"),
    ],
)
def test_unsupported_day_is_reported_as_domain_error(day: date, zone: str, code: str) -> None:
    with pytest.raises(PlannerTimeError) as error:
        make_time_grid(context(day=day, zone=zone))
    assert (error.value.field, error.value.code) == ("day", code)


@pytest.mark.parametrize(
    ("day", "zone", "expected"),
    [
        (date(2024, 2, 29), "UTC", datetime(2024, 3, 1, tzinfo=UTC)),
        (date(2026, 3, 29), "Europe/Berlin", datetime(2026, 3, 29, 22, tzinfo=UTC)),
        (date(2026, 10, 25), "Europe/Berlin", datetime(2026, 10, 25, 23, tzinfo=UTC)),
        (date(2026, 11, 14), "Asia/Yekaterinburg", datetime(2026, 11, 14, 19, tzinfo=UTC)),
    ],
)
def test_date_deadline_ends_at_next_local_midnight(
    day: date, zone: str, expected: datetime
) -> None:
    assert deadline_boundary(day, zone) == expected
    assert deadline_boundary(None, zone) is None


@pytest.mark.parametrize(
    ("deadline", "zone", "field", "code"),
    [
        (datetime(2026, 11, 14, tzinfo=UTC), "UTC", "deadline", "INVALID_DATE"),
        (date.max, "UTC", "deadline", "DATE_RANGE_UNSUPPORTED"),
        (date(2011, 12, 30), "Pacific/Apia", "deadline", "LOCAL_DATE_NONEXISTENT"),
        (DAY, "Missing/Zone", "timezone", "TIMEZONE_INVALID"),
    ],
)
def test_invalid_date_deadline_is_not_guessed(
    deadline: Any, zone: str, field: str, code: str
) -> None:
    with pytest.raises(PlannerTimeError) as error:
        deadline_boundary(deadline, zone)
    assert (error.value.field, error.value.code) == (field, code)


@given(duration=st.integers(5, 480), offset_us=st.integers(-1_000_000, 600 * 60 * 1_000_000))
def test_property_candidates_are_exact_future_aligned_and_inside_window(
    duration: int, offset_us: int
) -> None:
    anchor = datetime.combine(DAY, time(8), UTC)
    now = anchor + timedelta(microseconds=offset_us)
    ctx = context(now=now)
    grid = make_time_grid(ctx)
    intervals = candidate_intervals(grid, duration)
    assert intervals == candidate_intervals(make_time_grid(ctx), duration)
    for item in intervals:
        assert item.start >= now
        assert item.end - item.start == timedelta(minutes=duration)
        assert grid.work_window.start <= item.start < item.end <= grid.work_window.end
        assert (item.start - anchor) % timedelta(minutes=15) == timedelta(0)
