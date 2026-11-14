from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.time import (
    FrozenClock,
    LocalTimeError,
    SystemClock,
    local_day_bounds,
    local_time_candidates,
    local_to_utc,
    parse_timezone,
    to_utc,
)


def test_clocks_return_aware_utc() -> None:
    instant = datetime(2026, 11, 7, 15, tzinfo=timezone(timedelta(hours=5)))
    clock = FrozenClock(instant)
    assert clock.now() == datetime(2026, 11, 7, 10, tzinfo=UTC)
    assert clock.now().tzinfo is UTC
    assert SystemClock().now().tzinfo is UTC


def test_naive_moments_are_rejected() -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        to_utc(datetime(2026, 11, 7))
    with pytest.raises(ValueError, match="часовой пояс"):
        FrozenClock(datetime(2026, 11, 7))


@pytest.mark.parametrize("name", ["Not/AZone", "../Europe/Berlin", "", "/etc/localtime"])
def test_invalid_timezone(name: str) -> None:
    with pytest.raises(ValueError, match="IANA"):
        parse_timezone(name)


def test_normal_local_time_to_utc() -> None:
    assert local_to_utc(datetime(2026, 11, 7, 15), ZoneInfo("Asia/Yekaterinburg")) == (
        datetime(2026, 11, 7, 10, tzinfo=UTC)
    )


def test_local_candidates_require_naive_datetime() -> None:
    with pytest.raises(ValueError, match="без часового пояса"):
        local_time_candidates(datetime(2026, 11, 7, tzinfo=UTC), ZoneInfo("UTC"))


@pytest.mark.parametrize(
    ("zone", "local", "code"),
    [
        ("Europe/Berlin", datetime(2026, 3, 29, 2, 30), "LOCAL_TIME_NONEXISTENT"),
        ("Europe/Berlin", datetime(2026, 10, 25, 2, 30), "LOCAL_TIME_AMBIGUOUS"),
        ("America/New_York", datetime(2026, 3, 8, 2, 30), "LOCAL_TIME_NONEXISTENT"),
        ("America/New_York", datetime(2026, 11, 1, 1, 30), "LOCAL_TIME_AMBIGUOUS"),
    ],
)
def test_dst_local_time_errors(zone: str, local: datetime, code: str) -> None:
    with pytest.raises(LocalTimeError) as error:
        local_to_utc(local, ZoneInfo(zone))
    assert error.value.code == code


@pytest.mark.parametrize(
    ("zone", "day", "hours"),
    [
        ("UTC", date(2026, 11, 7), 24),
        ("Asia/Yekaterinburg", date(2026, 11, 7), 24),
        ("Europe/Moscow", date(2026, 11, 7), 24),
        ("Europe/Berlin", date(2026, 3, 29), 23),
        ("Europe/Berlin", date(2026, 10, 25), 25),
        ("America/New_York", date(2026, 3, 8), 23),
        ("America/New_York", date(2026, 11, 1), 25),
        ("UTC", date(2024, 2, 29), 24),
    ],
)
def test_local_day_duration(zone: str, day: date, hours: int) -> None:
    tz = ZoneInfo(zone)
    start, end = local_day_bounds(day, tz)
    assert start.tzinfo is UTC and end.tzinfo is UTC
    assert end - start == timedelta(hours=hours)
    assert start.astimezone(tz).date() == day
    assert (end - timedelta(microseconds=1)).astimezone(tz).date() == day


def test_skipped_midnight_uses_first_existing_time() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    start, end = local_day_bounds(date(2018, 11, 4), tz)
    assert start == datetime(2018, 11, 4, 3, tzinfo=UTC)
    assert start.astimezone(tz).hour == 1
    assert end - start == timedelta(hours=23)


def test_repeated_midnight_uses_earlier_instant() -> None:
    tz = ZoneInfo("America/Havana")
    day = date(2020, 11, 1)
    candidates = local_time_candidates(datetime(2020, 11, 1), tz)
    assert len(candidates) == 2
    start, end = local_day_bounds(day, tz)
    assert start == candidates[0]
    assert end - start == timedelta(hours=25)


def test_skipped_date_is_rejected_but_previous_day_has_valid_end() -> None:
    tz = ZoneInfo("Pacific/Apia")
    with pytest.raises(LocalTimeError) as error:
        local_day_bounds(date(2011, 12, 30), tz)
    assert error.value.code == "LOCAL_DATE_NONEXISTENT"
    start, end = local_day_bounds(date(2011, 12, 29), tz)
    following, _ = local_day_bounds(date(2011, 12, 31), tz)
    assert end == following
    assert end - start == timedelta(hours=24)
