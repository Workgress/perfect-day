from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from math import sin, tau
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.core.time import FrozenClock
from app.modules.users.dependencies import get_clock
from tests.integration.test_profile_biorhythm_api import ProfileAPI
from tests.integration.test_profile_biorhythm_api import alembic_config as alembic_config
from tests.integration.test_profile_biorhythm_api import auth_api as auth_api
from tests.integration.test_profile_biorhythm_api import engine as engine
from tests.integration.test_profile_biorhythm_api import migrated_url as migrated_url
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

pytestmark = pytest.mark.docker
BIRTH = datetime(2000, 1, 1, 12, tzinfo=UTC)
# Deliberately independent of the engine's constants and calculation helpers.
PERIODS = {"physical": 23, "emotional": 28, "intellectual": 33}


def instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def assert_scalar_values(cycles: dict, birth: datetime, at: datetime) -> None:
    seconds = (at - birth).total_seconds()
    for cycle, period in PERIODS.items():
        expected = sin(tau * ((seconds % (period * 86400)) / (period * 86400)))
        assert cycles[cycle]["value"] == pytest.approx(expected, abs=1e-12)
        assert -1 <= cycles[cycle]["value"] <= 1
        assert cycles[cycle]["percent"] == round(expected * 1000) / 10


@pytest.mark.parametrize("cycle", PERIODS)
@pytest.mark.parametrize(
    ("quarter", "value", "phase", "trend"),
    [
        (0, 0, "rising", "up"),
        (1, 1, "peak", "down"),
        (2, 0, "rising", "down"),
        (3, -1, "minimum", "up"),
    ],
)
async def test_api_quarter_periods_match_manual_values_and_hourly_series(
    profile_api: ProfileAPI, cycle: str, quarter: int, value: int, phase: str, trend: str
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"birth_time": "00:00:00"})).status_code == 200
    birth = BIRTH.replace(hour=0)
    at = birth + timedelta(days=PERIODS[cycle] * quarter / 4)
    response = await profile_api.get(f"/biorhythms/now?at={instant(at)}")
    assert response.status_code == 200
    body = response.json()
    assert body["at"] == instant(at)
    assert body["cycles"][cycle] == {
        "value": value,
        "percent": value * 100,
        "phase": phase,
        "trend": trend,
    }
    assert_scalar_values(body["cycles"], birth, at)
    series = await profile_api.get(f"/biorhythms?from={at.date()}&to={at.date()}&step=hour")
    assert series.status_code == 200
    point = next(point for point in series.json()["points"] if point["at"] == body["at"])
    assert point["cycles"] == body["cycles"]
    assert point["critical"] == body["critical"]


@pytest.mark.parametrize(
    ("twelfths", "offset_seconds", "phase", "percent"),
    [(1, -1, "rising", 50), (1, 0, "peak", 50), (7, -1, "declining", -50), (7, 0, "minimum", -50)],
)
async def test_api_phase_uses_unrounded_value(
    profile_api: ProfileAPI, twelfths: int, offset_seconds: int, phase: str, percent: int
) -> None:
    await profile_api.complete()
    at = BIRTH + timedelta(days=23 * twelfths / 12, seconds=offset_seconds)
    response = await profile_api.get(f"/biorhythms/now?at={instant(at)}")
    assert response.status_code == 200
    physical = response.json()["cycles"]["physical"]
    assert physical["percent"] == percent
    assert physical["phase"] == phase
    if offset_seconds == 0:
        assert physical["value"] == percent / 100
    else:
        assert abs(physical["value"]) < 0.5


@pytest.mark.parametrize(
    ("offset", "crossings"),
    [
        (0, [("physical", 0), ("emotional", 0), ("intellectual", 0)]),
        (11.5, [("physical", 11.5)]),
        (14, [("emotional", 14)]),
        (16.5, [("intellectual", 16.5)]),
        (126, [("emotional", 126), ("physical", 126.5)]),
        (322, [("physical", 322), ("emotional", 322)]),
        (379.5, [("physical", 379.5), ("intellectual", 379.5)]),
        (10626, [("physical", 10626), ("emotional", 10626), ("intellectual", 10626)]),
    ],
)
async def test_critical_days_api_matches_analytical_crossings(
    profile_api: ProfileAPI, offset: float, crossings: list[tuple[str, float]]
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"birth_time": "00:00:00"})).status_code == 200
    birth = BIRTH.replace(hour=0)
    day = (birth + timedelta(days=offset)).date()
    response = await profile_api.get(f"/biorhythms/critical-days?from={day}&to={day}")
    assert response.status_code == 200
    level = len(crossings)
    critical = {
        "level": level,
        "kind": {1: "single", 2: "double", 3: "triple"}[level],
        "crossings": [
            {"cycle": cycle, "at": instant(birth + timedelta(days=days))}
            for cycle, days in crossings
        ],
    }
    assert response.json()["days"] == [{"date": str(day), **critical}]
    series = await profile_api.get(f"/biorhythms?from={day}&to={day}&step=hour")
    assert series.status_code == 200
    assert all(point["critical"] == critical for point in series.json()["points"])


@pytest.mark.parametrize(
    ("zone", "day"),
    [
        ("UTC", date(2026, 10, 25)),
        ("Asia/Yekaterinburg", date(2026, 10, 25)),
        ("Europe/Berlin", date(2026, 10, 25)),
        ("America/New_York", date(2026, 11, 1)),
    ],
)
@pytest.mark.parametrize("minutes", [-1, 0, 1])
async def test_critical_crossing_belongs_to_exactly_one_local_day(
    profile_api: ProfileAPI, zone: str, day: date, minutes: int
) -> None:
    await profile_api.complete()
    tz = ZoneInfo(zone)
    boundary = datetime.combine(day, time.min, tz).astimezone(UTC)
    crossing = boundary + timedelta(minutes=minutes)
    birth = crossing - timedelta(days=11.5)
    assert (
        await profile_api.patch(
            {
                "birth_date": str(birth.date()),
                "birth_time": birth.strftime("%H:%M:00"),
                "timezone": zone,
            }
        )
    ).status_code == 200
    previous_day = day - timedelta(days=1)
    response = await profile_api.get(f"/biorhythms/critical-days?from={previous_day}&to={day}")
    assert response.status_code == 200
    found = [
        (item["date"], event)
        for item in response.json()["days"]
        for event in item["crossings"]
        if event["cycle"] == "physical"
    ]
    expected_day = previous_day if minutes < 0 else day
    assert found == [(str(expected_day), {"cycle": "physical", "at": instant(crossing)})]
    now = await profile_api.get(f"/biorhythms/now?at={instant(crossing)}")
    assert now.status_code == 200
    assert now.json()["date"] == str(expected_day)
    assert now.json()["cycles"]["physical"]["value"] == 0


@pytest.mark.parametrize(
    ("zone", "day", "count"),
    [
        ("UTC", "2024-02-29", 24),
        ("Europe/Berlin", "2026-03-29", 23),
        ("Europe/Berlin", "2026-10-25", 25),
        ("America/New_York", "2026-03-08", 23),
        ("America/New_York", "2026-11-01", 25),
        ("Australia/Lord_Howe", "2026-04-05", 25),
        ("Australia/Lord_Howe", "2026-10-04", 24),
    ],
)
async def test_hourly_api_grid_handles_dst_and_leap_dates(
    profile_api: ProfileAPI, zone: str, day: str, count: int
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": zone})).status_code == 200
    response = await profile_api.get(f"/biorhythms?from={day}&to={day}&step=hour")
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == zone
    assert len(body["points"]) == count
    moments = [datetime.fromisoformat(point["at"]) for point in body["points"]]
    assert moments == sorted(set(moments))
    assert all(right - left == timedelta(hours=1) for left, right in pairwise(moments))
    for point, at in zip(body["points"], moments, strict=True):
        assert point["date"] == day == str(at.astimezone(ZoneInfo(zone)).date())
        assert_scalar_values(point["cycles"], BIRTH, at)


async def test_daily_api_grid_includes_leap_day_at_local_noon(profile_api: ProfileAPI) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": "Asia/Yekaterinburg"})).status_code == 200
    response = await profile_api.get("/biorhythms?from=2024-02-28&to=2024-03-01&step=day")
    assert response.status_code == 200
    assert [point["date"] for point in response.json()["points"]] == [
        "2024-02-28",
        "2024-02-29",
        "2024-03-01",
    ]
    for point in response.json()["points"]:
        at = datetime.fromisoformat(point["at"])
        assert at.hour == 7
        assert_scalar_values(point["cycles"], BIRTH, at)


@pytest.mark.parametrize(
    ("now", "zone", "period", "start", "end", "count", "step"),
    [
        ("2026-03-29T10:00:00Z", "Europe/Berlin", "day", "2026-03-29", "2026-03-29", 23, "hour"),
        ("2026-10-25T10:00:00Z", "Europe/Berlin", "day", "2026-10-25", "2026-10-25", 25, "hour"),
        (
            "2026-11-08T22:00:00Z",
            "Asia/Yekaterinburg",
            "week",
            "2026-11-09",
            "2026-11-15",
            7,
            "day",
        ),
        ("2024-01-31T10:00:00Z", "UTC", "month", "2024-01-31", "2024-02-28", 29, "day"),
    ],
)
async def test_forecast_api_uses_current_local_date_and_calendar_period(
    profile_api: ProfileAPI,
    now: str,
    zone: str,
    period: str,
    start: str,
    end: str,
    count: int,
    step: str,
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": zone})).status_code == 200
    profile_api.api.app.dependency_overrides[get_clock] = lambda: FrozenClock(
        datetime.fromisoformat(now)
    )
    response = await profile_api.get(f"/biorhythms/forecast?period={period}")
    assert response.status_code == 200
    body = response.json()
    assert (body["start"], body["end"], body["period"], body["step"]) == (start, end, period, step)
    assert len(body["points"]) == count
    for point in body["points"]:
        assert_scalar_values(point["cycles"], BIRTH, datetime.fromisoformat(point["at"]))


@pytest.mark.parametrize(
    ("path", "zone", "field"),
    [
        ("/biorhythms/now?at=9999999999", "UTC", "at"),
        ("/biorhythms/now?at=1700000000.5", "UTC", "at"),
        ("/biorhythms/now?at=9999-12-31T23:59:59Z", "Pacific/Kiritimati", "at"),
        ("/biorhythms/now?at=2000-01-01T11:59:59.999999Z", "UTC", "at"),
        ("/biorhythms?from=9999-12-31&to=9999-12-31", "UTC", "from"),
        ("/biorhythms?from=2000-01-01&to=2000-01-01&step=hour", "UTC", "from"),
        ("/biorhythms/critical-days?from=2000-01-01&to=2000-01-01", "UTC", "from"),
        ("/biorhythms?from=2011-12-29&to=2011-12-31", "Pacific/Apia", "from"),
        ("/biorhythms?from=2011-12-29&to=2011-12-31&step=hour", "Pacific/Apia", "from"),
        ("/biorhythms/critical-days?from=2011-12-29&to=2011-12-31", "Pacific/Apia", "from"),
    ],
)
async def test_invalid_parameters_are_rejected_before_any_cache_access(
    profile_api: ProfileAPI, path: str, zone: str, field: str
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": zone})).status_code == 200
    with patch.object(
        profile_api.cache.backend, "get", side_effect=AssertionError("invalid request read cache")
    ):
        response = await profile_api.get(path)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"][0]["field"] == f"query.{field}"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("step", "count"), [("day", 62), ("hour", 1489)])
async def test_api_range_limit_accepts_62_days_and_rejects_63(
    profile_api: ProfileAPI, step: str, count: int
) -> None:
    await profile_api.complete()
    assert (await profile_api.patch({"timezone": "Europe/Berlin"})).status_code == 200
    valid = await profile_api.get(f"/biorhythms?from=2026-09-01&to=2026-11-01&step={step}")
    assert valid.status_code == 200
    assert len(valid.json()["points"]) == count
    with patch.object(
        profile_api.cache.backend, "get", side_effect=AssertionError("invalid request read cache")
    ):
        for path in ("/biorhythms", "/biorhythms/critical-days"):
            suffix = f"&step={step}" if path == "/biorhythms" else ""
            invalid = await profile_api.get(f"{path}?from=2026-09-01&to=2026-11-02{suffix}")
            assert invalid.status_code == 422
            field = invalid.json()["error"]["details"]["fields"][0]
            assert (field["field"], field["code"]) == ("query.to", "RANGE_TOO_LONG")
