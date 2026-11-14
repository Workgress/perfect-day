from datetime import UTC, date, datetime, timedelta
from math import sin, tau
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.time import LocalTimeError, local_day_bounds
from app.modules.biorhythm.config import CYCLES, PERIODS
from app.modules.biorhythm.engine import critical_info, cycle_value
from app.modules.biorhythm.types import CriticalCrossing, CriticalKind, Cycle

BIRTH = datetime(2000, 1, 1, tzinfo=UTC)
UTC_ZONE = ZoneInfo("UTC")


def _reference_sign(birth: datetime, at: datetime, cycle: Cycle) -> int:
    days = (at - birth).total_seconds() / 86400
    value = sin(tau * days / PERIODS[cycle])
    return 0 if abs(value) < 1e-10 else (1 if value > 0 else -1)


def test_day_without_crossings() -> None:
    info = critical_info(BIRTH, date(2000, 1, 2), UTC_ZONE)
    assert info.level == 0
    assert info.kind is CriticalKind.NONE
    assert info.crossings == ()


@pytest.mark.parametrize("cycle", CYCLES)
def test_single_critical_day_has_exact_crossing(cycle: Cycle) -> None:
    at = BIRTH + timedelta(days=PERIODS[cycle] / 2)
    info = critical_info(BIRTH, at.date(), UTC_ZONE)
    assert info.level == 1
    assert info.kind is CriticalKind.SINGLE
    assert info.crossings == (CriticalCrossing(cycle, at),)
    assert info.crossings[0].at.tzinfo is UTC
    assert cycle_value(BIRTH, at, cycle) == 0.0


@pytest.mark.parametrize(
    ("days", "cycles"),
    [
        (322, (Cycle.PHYSICAL, Cycle.EMOTIONAL)),
        (379.5, (Cycle.PHYSICAL, Cycle.INTELLECTUAL)),
        (462, (Cycle.EMOTIONAL, Cycle.INTELLECTUAL)),
    ],
)
def test_double_critical_day_at_coincident_crossings(
    days: float, cycles: tuple[Cycle, ...]
) -> None:
    at = BIRTH + timedelta(days=days)
    info = critical_info(BIRTH, at.date(), UTC_ZONE)
    assert info.level == 2
    assert info.kind is CriticalKind.DOUBLE
    assert tuple(crossing.cycle for crossing in info.crossings) == cycles
    assert all(crossing.at == at for crossing in info.crossings)


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(days=10626)])
def test_triple_critical_day_at_birth_and_common_half_period(offset: timedelta) -> None:
    birth = BIRTH + timedelta(hours=12)
    at = birth + offset
    info = critical_info(birth, at.date(), UTC_ZONE)
    assert info.level == 3
    assert info.kind is CriticalKind.TRIPLE
    assert info.crossings == tuple(CriticalCrossing(cycle, at) for cycle in CYCLES)


def test_multiple_crossings_are_sorted_by_time_before_cycle_order() -> None:
    day = (BIRTH + timedelta(days=126)).date()
    info = critical_info(BIRTH, day, UTC_ZONE)
    assert info.level == 2 and info.kind is CriticalKind.DOUBLE
    assert info.crossings == (
        CriticalCrossing(Cycle.EMOTIONAL, BIRTH + timedelta(days=126)),
        CriticalCrossing(Cycle.PHYSICAL, BIRTH + timedelta(days=126, hours=12)),
    )


@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"])
@pytest.mark.parametrize("delta_us", [-1, 0, 1])
def test_midnight_assignment_is_exact_to_microsecond(zone: str, delta_us: int) -> None:
    tz = ZoneInfo(zone)
    day = date(2026, 10, 25)
    boundary, _ = local_day_bounds(day, tz)
    at = boundary + timedelta(microseconds=delta_us)
    birth = at - timedelta(days=11.5)
    previous = critical_info(birth, day - timedelta(days=1), tz)
    current = critical_info(birth, day, tz)
    event = CriticalCrossing(Cycle.PHYSICAL, at)
    assert (event in current.crossings) is (delta_us >= 0)
    assert (event in previous.crossings) is (delta_us < 0)
    assert sum(event in info.crossings for info in (previous, current)) == 1


def test_crossing_at_day_end_belongs_to_next_day() -> None:
    day = date(2026, 11, 7)
    _, at = local_day_bounds(day, ZoneInfo("Asia/Yekaterinburg"))
    birth = at - timedelta(days=14)
    event = CriticalCrossing(Cycle.EMOTIONAL, at)
    assert event not in critical_info(birth, day, ZoneInfo("Asia/Yekaterinburg")).crossings
    assert (
        event
        in critical_info(birth, day + timedelta(days=1), ZoneInfo("Asia/Yekaterinburg")).crossings
    )


def test_timezone_moves_event_to_different_local_date() -> None:
    at = datetime(2026, 11, 7, 22, 30, tzinfo=UTC)
    birth = at - timedelta(days=11.5)
    tz = ZoneInfo("Asia/Yekaterinburg")
    event = CriticalCrossing(Cycle.PHYSICAL, at)
    assert event in critical_info(birth, date(2026, 11, 7), UTC_ZONE).crossings
    assert event not in critical_info(birth, date(2026, 11, 7), tz).crossings
    assert event in critical_info(birth, date(2026, 11, 8), tz).crossings
    assert at.astimezone(tz).isoformat() == "2026-11-08T03:30:00+05:00"


@pytest.mark.parametrize(
    ("zone", "day"),
    [("Europe/Berlin", date(2026, 10, 25)), ("America/New_York", date(2026, 11, 1))],
)
def test_crossing_in_extra_hour_of_long_day_is_included(zone: str, day: date) -> None:
    tz = ZoneInfo(zone)
    start, end = local_day_bounds(day, tz)
    assert end - start == timedelta(hours=25)
    at = start + timedelta(hours=24, minutes=30)
    info = critical_info(at - timedelta(days=11.5), day, tz)
    assert info.crossings == (CriticalCrossing(Cycle.PHYSICAL, at),)


@pytest.mark.parametrize(
    ("zone", "day"),
    [("Europe/Berlin", date(2026, 3, 29)), ("America/New_York", date(2026, 3, 8))],
)
def test_crossing_after_short_day_is_excluded(zone: str, day: date) -> None:
    tz = ZoneInfo(zone)
    start, end = local_day_bounds(day, tz)
    assert end - start == timedelta(hours=23)
    at = start + timedelta(hours=23, minutes=30)
    birth = at - timedelta(days=11.5)
    event = CriticalCrossing(Cycle.PHYSICAL, at)
    assert event not in critical_info(birth, day, tz).crossings
    assert event in critical_info(birth, day + timedelta(days=1), tz).crossings


@pytest.mark.parametrize("fold", [0, 1])
def test_crossing_inside_repeated_hour_preserves_exact_utc_instant(fold: int) -> None:
    tz = ZoneInfo("Europe/Berlin")
    at = datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=fold).astimezone(UTC)
    info = critical_info(at - timedelta(days=11.5), date(2026, 10, 25), tz)
    assert info.crossings == (CriticalCrossing(Cycle.PHYSICAL, at),)
    assert info.crossings[0].at.astimezone(tz).fold == fold


def test_crossing_when_midnight_was_skipped() -> None:
    tz = ZoneInfo("America/Sao_Paulo")
    at = datetime(2018, 11, 4, 3, tzinfo=UTC)  # first existing moment: 01:00 local
    info = critical_info(at - timedelta(days=11.5), date(2018, 11, 4), tz)
    assert info.crossings == (CriticalCrossing(Cycle.PHYSICAL, at),)
    assert info.crossings[0].at.astimezone(tz).hour == 1


def test_fully_skipped_local_date_is_rejected() -> None:
    with pytest.raises(LocalTimeError) as error:
        critical_info(BIRTH, date(2011, 12, 30), ZoneInfo("Pacific/Apia"))
    assert error.value.code == "LOCAL_DATE_NONEXISTENT"


def test_negative_cycle_indices_are_supported_in_pure_engine() -> None:
    at = BIRTH - timedelta(days=11.5)
    info = critical_info(BIRTH, at.date(), UTC_ZONE)
    assert info.crossings == (CriticalCrossing(Cycle.PHYSICAL, at),)


def test_naive_birth_is_rejected() -> None:
    with pytest.raises(ValueError, match="часовой пояс"):
        critical_info(datetime(2000, 1, 1), date(2026, 11, 7), UTC_ZONE)


def test_aware_birth_in_another_timezone_produces_identical_result() -> None:
    day = date(2000, 1, 12)
    assert critical_info(BIRTH, day, UTC_ZONE) == critical_info(
        BIRTH.astimezone(ZoneInfo("Asia/Yekaterinburg")), day, UTC_ZONE
    )


@pytest.mark.parametrize("cycle", CYCLES)
@pytest.mark.parametrize("period_count", [1, 2, 3])
def test_crossing_count_in_whole_periods(cycle: Cycle, period_count: int) -> None:
    days = PERIODS[cycle] * period_count
    count = sum(
        crossing.cycle is cycle
        for offset in range(days)
        for crossing in critical_info(
            BIRTH, BIRTH.date() + timedelta(days=offset), UTC_ZONE
        ).crossings
    )
    assert count == 2 * period_count


def test_critical_day_count_has_no_monthly_two_to_three_assumption() -> None:
    # A 31-day interval can contain three emotional crossings: t=0, 14, 28.
    count = sum(
        crossing.cycle is Cycle.EMOTIONAL
        for day in range(31)
        for crossing in critical_info(BIRTH, BIRTH.date() + timedelta(days=day), UTC_ZONE).crossings
    )
    assert count == 3
    # A 28-day interval just after t=0 contains only one intellectual crossing.
    count = sum(
        crossing.cycle is Cycle.INTELLECTUAL
        for day in range(1, 29)
        for crossing in critical_info(BIRTH, BIRTH.date() + timedelta(days=day), UTC_ZONE).crossings
    )
    assert count == 1


@pytest.mark.parametrize("zone", ["UTC", "Europe/Berlin", "America/New_York"])
def test_analytical_days_match_independent_hourly_sign_scan(zone: str) -> None:
    tz = ZoneInfo(zone)
    birth = datetime(1995, 3, 14, 7, 23, 45, tzinfo=UTC)
    for day_offset in range(35):
        day = date(2026, 3, 7) + timedelta(days=day_offset)
        start, end = local_day_bounds(day, tz)
        expected = set()
        for cycle in CYCLES:
            at = start
            while at < end:
                next_at = min(at + timedelta(hours=1), end)
                left = _reference_sign(birth, at, cycle)
                right = _reference_sign(birth, next_at, cycle)
                if left == 0 or left * right < 0:
                    expected.add(cycle)
                at = next_at
        info = critical_info(birth, day, tz)
        assert {crossing.cycle for crossing in info.crossings} == expected


@given(
    day_offset=st.integers(-500, 500),
    birth_microseconds=st.integers(0, 999999),
    zone=st.sampled_from(["UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"]),
)
def test_property_exact_candidates_in_local_day(
    day_offset: int, birth_microseconds: int, zone: str
) -> None:
    birth = BIRTH + timedelta(hours=12, microseconds=birth_microseconds)
    day = BIRTH.date() + timedelta(days=day_offset)
    tz = ZoneInfo(zone)
    start, end = local_day_bounds(day, tz)
    # Independent finite enumeration of roots, not the integer-ceil algorithm.
    expected = []
    for cycle in CYCLES:
        for index in range(-50, 51):
            at = birth + timedelta(days=index * PERIODS[cycle] / 2)
            if start <= at < end:
                expected.append(CriticalCrossing(cycle, at))
    expected.sort(key=lambda crossing: (crossing.at, CYCLES.index(crossing.cycle)))
    info = critical_info(birth, day, tz)
    assert info.crossings == tuple(expected)
    assert info.level == len({crossing.cycle for crossing in expected})
    assert info.kind is tuple(CriticalKind)[info.level]
    for crossing in info.crossings:
        assert crossing.at.astimezone(tz).date() == day
        assert cycle_value(birth, crossing.at, crossing.cycle) == 0.0
