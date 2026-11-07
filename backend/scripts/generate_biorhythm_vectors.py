"""Run: uv run python -m scripts.generate_biorhythm_vectors [--check]."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from app.modules.biorhythm import engine
from app.modules.biorhythm.config import ALGORITHM_VERSION, CYCLES, PERIODS
from app.modules.biorhythm.types import (
    BiorhythmSnapshot,
    CriticalDay,
    CriticalDays,
    Forecast,
    ForecastPeriod,
    Step,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
BIRTH = datetime(2000, 1, 1, tzinfo=UTC)
EXAMPLE_NOW = datetime(2026, 11, 8, 10, tzinfo=UTC)
ZONES = ("UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York")
SNAPSHOT_ADAPTER = TypeAdapter(BiorhythmSnapshot)
type Document = dict[str, Any]


@dataclass(frozen=True)
class Case:
    id: str
    birth_date: date
    birth_time: time | None
    timezone: str
    at: datetime
    tags: tuple[str, ...]

    @property
    def birth(self) -> datetime:
        return datetime.combine(self.birth_date, self.birth_time or time(12), UTC)

    def vector(self) -> Document:
        return {
            "id": self.id,
            "tags": list(self.tags),
            "input": {
                "profile": {
                    "birth_date": self.birth_date.isoformat(),
                    "birth_time": self.birth_time.isoformat()
                    if self.birth_time is not None
                    else None,
                    "timezone": self.timezone,
                },
                "at": utc_string(self.at),
            },
            "expected": snapshot(self.birth, self.at, self.timezone),
        }


def utc_string(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def snapshot(birth: datetime, at: datetime, zone: str) -> Document:
    tz = ZoneInfo(zone)
    day = at.astimezone(tz).date()
    state = engine.snapshot(birth, at)
    result = BiorhythmSnapshot(
        ALGORITHM_VERSION, zone, state.at, day, state.cycles, engine.critical_info(birth, day, tz)
    )
    return cast(Document, SNAPSHOT_ADAPTER.dump_python(result, mode="json"))


def make_cases() -> list[Case]:
    cases = []
    anchor = EXAMPLE_NOW.replace(microsecond=123456)
    for zone in ZONES:
        for known, birth_time in (("known", time(6, 30)), ("unknown", None)):
            for index in range(10):
                cases.append(
                    Case(
                        f"ordinary-{zone}-{known}-{index}",
                        date(2000, 2, 29),
                        birth_time,
                        zone,
                        anchor + timedelta(hours=37 * index),
                        ("ordinary", "leap_birth", known),
                    )
                )

    cases.append(Case("birth-zero", BIRTH.date(), time.min, "UTC", BIRTH, ("manual", "triple")))
    offsets = (("before", -1), ("exact", 0), ("after", 1))
    for cycle in CYCLES:
        period_seconds = PERIODS[cycle] * 86400
        for quarter in (1, 2, 3, 4):
            at = BIRTH + timedelta(seconds=period_seconds * quarter // 4)
            for suffix, microseconds in offsets:
                cases.append(
                    Case(
                        f"quarter-{cycle}-{quarter}-{suffix}",
                        BIRTH.date(),
                        time.min,
                        "UTC",
                        at + timedelta(microseconds=microseconds),
                        ("quarter", cycle.value, suffix),
                    )
                )
        for twelfth in (1, 5, 7, 11):
            at = BIRTH + timedelta(seconds=period_seconds * twelfth // 12)
            for suffix, microseconds in offsets:
                cases.append(
                    Case(
                        f"phase-{cycle}-{twelfth}-{suffix}",
                        BIRTH.date(),
                        time.min,
                        "UTC",
                        at + timedelta(microseconds=microseconds),
                        ("phase_boundary", cycle.value, suffix),
                    )
                )

    for days in (11.5, 14, 16.5, 126, 322, 379.5, 462, 10626):
        for zone in ZONES:
            at = BIRTH + timedelta(days=days)
            cases.append(
                Case(
                    f"critical-{days}-{zone}",
                    BIRTH.date(),
                    time.min,
                    zone,
                    at,
                    ("critical",),
                )
            )

    for zone in ZONES:
        tz = ZoneInfo(zone)
        boundary = datetime(2026, 10, 25, tzinfo=tz).astimezone(UTC)
        birth = boundary - timedelta(days=11.5)
        for suffix, microseconds in offsets:
            cases.append(
                Case(
                    f"midnight-{zone}-{suffix}",
                    birth.date(),
                    birth.time(),
                    zone,
                    boundary + timedelta(microseconds=microseconds),
                    ("midnight", suffix),
                )
            )

    transitions = (
        ("Europe/Berlin", date(2026, 3, 29)),
        ("Europe/Berlin", date(2026, 10, 25)),
        ("America/New_York", date(2026, 3, 8)),
        ("America/New_York", date(2026, 11, 1)),
        ("Australia/Lord_Howe", date(2026, 4, 5)),
        ("Australia/Lord_Howe", date(2026, 10, 4)),
    )
    for zone, day in transitions:
        for index, at in enumerate(engine.time_grid(day, 1, ZoneInfo(zone), Step.HOUR)):
            cases.append(
                Case(
                    f"dst-{zone}-{day}-{index}",
                    BIRTH.date(),
                    time.min,
                    zone,
                    at,
                    ("dst", "hourly"),
                )
            )

    for zone in ZONES:
        for index, at in enumerate(
            (
                datetime(2024, 2, 28, 23, 59, 59, 999999, UTC),
                datetime(2024, 2, 29, tzinfo=UTC),
                datetime(2024, 2, 29, 12, tzinfo=UTC),
                datetime(2024, 3, 1, tzinfo=UTC),
            )
        ):
            cases.append(
                Case(
                    f"leap-{zone}-{index}",
                    BIRTH.date(),
                    None,
                    zone,
                    at,
                    ("leap_day", "unknown"),
                )
            )
    for suffix, microseconds in offsets:
        cases.append(
            Case(
                f"date-jump-{suffix}",
                BIRTH.date(),
                time.min,
                "Pacific/Apia",
                datetime(2011, 12, 30, 10, tzinfo=UTC) + timedelta(microseconds=microseconds),
                ("skipped_date", suffix),
            )
        )
    return cases


def manual_controls() -> list[Document]:
    controls = []
    quarters = {
        1: (1.0, 100.0, "peak", "down"),
        2: (0.0, 0.0, "rising", "down"),
        3: (-1.0, -100.0, "minimum", "up"),
        4: (0.0, 0.0, "rising", "up"),
    }
    phases = {
        1: (0.5, 50.0, "peak", "up"),
        5: (0.5, 50.0, "peak", "down"),
        7: (-0.5, -50.0, "minimum", "down"),
        11: (-0.5, -50.0, "minimum", "up"),
    }
    for cycle in ("physical", "emotional", "intellectual"):
        controls.append(
            {
                "vector_id": "birth-zero",
                "cycle": cycle,
                "expected": {"value": 0.0, "percent": 0.0, "phase": "rising", "trend": "up"},
            }
        )
        for prefix, table in (("quarter", quarters), ("phase", phases)):
            for part, (value, percent, phase, trend) in table.items():
                controls.append(
                    {
                        "vector_id": f"{prefix}-{cycle}-{part}-exact",
                        "cycle": cycle,
                        "expected": {
                            "value": value,
                            "percent": percent,
                            "phase": phase,
                            "trend": trend,
                        },
                    }
                )
    return controls


def vectors_document() -> Document:
    return {
        "schema_version": 1,
        "algorithm_version": ALGORITHM_VERSION,
        "comparison": {
            "value_absolute_tolerance": 1e-12,
            "value_decimal_places": 12,
            "other_fields": "exact",
        },
        "rules": {
            "period_days": dict(PERIODS),
            "day_seconds": 86400,
            "value_formula": "sin(2*pi*((at_utc-birth_utc)/86400)/period_days)",
            "birth_scale": "UTC",
            "unknown_birth_time": "12:00:00",
            "normalization_boundaries": [-1, -0.5, 0, 0.5, 1],
            "numerical_tolerance": 1e-12,
            "percent_formula": "roundTiesToEven(value*1000)/10; zero is positive",
            "critical_interval": "[local_day_start, next_local_day_start)",
        },
        "manual_controls": manual_controls(),
        "rounding_controls": [
            {"value": value, "percent": percent}
            for value, percent in (
                (0.1235, 12.4),
                (0.1245, 12.4),
                (-0.1235, -12.4),
                (-0.1245, -12.4),
                (0.0005, 0.0),
                (0.0015, 0.2),
                (-0.0004, 0.0),
                (-0.0, 0.0),
            )
        ],
        "vectors": [case.vector() for case in make_cases()],
    }


def examples_document() -> Document:
    birth = BIRTH.replace(hour=12)
    profile = {
        "birth_date": "2000-01-01",
        "birth_time": "12:00:00",
        "timezone": "UTC",
        "chronotype": "dove",
        "work_start": "08:00:00",
        "work_end": "18:00:00",
        "sleep_time": "23:00:00",
    }
    document = {
        "id": "11111111-1111-4111-8111-111111111111",
        "email": "person@example.test",
        "display_name": None,
        "profile": profile,
        "onboarding": {"completed_at": utc_string(EXAMPLE_NOW), "next_step": None},
    }
    series = engine.forecast(birth, EXAMPLE_NOW.date(), 2, ZoneInfo("UTC"))
    forecast = engine.forecast_for_period(birth, EXAMPLE_NOW, ForecastPeriod.WEEK, ZoneInfo("UTC"))
    end = EXAMPLE_NOW.date() + timedelta(days=6)
    days = []
    for offset in range(7):
        day = EXAMPLE_NOW.date() + timedelta(days=offset)
        critical = engine.critical_info(birth, day, ZoneInfo("UTC"))
        if critical.level:
            days.append(CriticalDay(day, critical.level, critical.kind, critical.crossings))
    critical_days = CriticalDays(ALGORITHM_VERSION, "UTC", EXAMPLE_NOW.date(), end, tuple(days))

    def example(method: str, path: str, response: Any, **request: Any) -> Document:
        return {
            "request": {"method": method, "path": f"/api/v1{path}", **request},
            "response": {"status": 200, "headers": {"Cache-Control": "no-store"}, "body": response},
        }

    return {
        "schema_version": 1,
        "algorithm_version": ALGORITHM_VERSION,
        "context": {
            "now": utc_string(EXAMPLE_NOW),
            "profile": profile,
            "onboarding_completed_at": utc_string(EXAMPLE_NOW),
            "authorization": "Bearer access token of a verified user",
        },
        "examples": {
            "me": example("GET", "/me", document),
            "patch_profile": example(
                "PATCH",
                "/me/profile",
                {**document, "profile": {**profile, "timezone": "Asia/Yekaterinburg"}},
                body={"timezone": "Asia/Yekaterinburg"},
            ),
            "now": example(
                "GET",
                "/biorhythms/now",
                snapshot(birth, EXAMPLE_NOW, "UTC"),
                query={"at": utc_string(EXAMPLE_NOW)},
            ),
            "series": example(
                "GET",
                "/biorhythms",
                TypeAdapter(Forecast).dump_python(series, mode="json"),
                query={"from": str(EXAMPLE_NOW.date()), "to": str(series.end), "step": "day"},
            ),
            "critical_days": example(
                "GET",
                "/biorhythms/critical-days",
                TypeAdapter(CriticalDays).dump_python(critical_days, mode="json"),
                query={"from": str(EXAMPLE_NOW.date()), "to": str(end)},
            ),
            "forecast": example(
                "GET",
                "/biorhythms/forecast",
                TypeAdapter(Forecast).dump_python(forecast, mode="json"),
                query={"period": "week"},
            ),
        },
    }


def _portable_values(value: Any) -> Any:
    """Discard platform-dependent final float bits only in exported examples."""
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _portable_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_values(item) for item in value]
    return value


def render(document: Document) -> bytes:
    return (
        json.dumps(_portable_values(document), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def generated_files() -> dict[str, bytes]:
    return {
        "biorhythm_vectors.json": render(vectors_document()),
        "biorhythm_api_examples.json": render(examples_document()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check without modifying files")
    args = parser.parse_args()
    changed = []
    for name, content in generated_files().items():
        path = FIXTURES_DIR / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                changed.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"Wrote {name}")
    if changed:
        print(f"Outdated fixtures: {', '.join(changed)}; regenerate without --check")
        return 1
    if args.check:
        print("Biorhythm fixtures are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
