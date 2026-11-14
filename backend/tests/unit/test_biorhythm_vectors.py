import json
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from math import ceil, copysign, cos, sin, tau
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter

from app.main import create_app
from app.modules.biorhythm import engine
from app.modules.biorhythm.config import ALGORITHM_VERSION
from app.modules.biorhythm.types import BiorhythmSnapshot, CriticalInfo
from app.modules.users.schemas import ProfilePatch
from scripts import generate_biorhythm_vectors as generator

DATA = json.loads((generator.FIXTURES_DIR / "biorhythm_vectors.json").read_text(encoding="utf-8"))
VECTORS = {vector["id"]: vector for vector in DATA["vectors"]}
# These are independent acceptance values, not imports of the engine's constants.
PERIODS = {"physical": 23, "emotional": 28, "intellectual": 33}
TOLERANCE = 1e-12
MICROSECOND = timedelta(microseconds=1)


def reference_cycle(birth: datetime, at: datetime, period: int) -> dict[str, Any]:
    elapsed_us = (at - birth) // MICROSECOND
    period_us = period * 86400 * 1_000_000
    angle = tau * ((elapsed_us % period_us) / period_us)
    value = sin(angle)
    for boundary in (-1.0, -0.5, 0.0, 0.5, 1.0):
        if abs(value - boundary) <= TOLERANCE:
            value = boundary
            break
    if value >= 0.5:
        phase = "peak"
    elif value >= 0:
        phase = "rising"
    elif value > -0.5:
        phase = "declining"
    else:
        phase = "minimum"
    derivative = cos(angle)
    if abs(derivative) <= TOLERANCE:
        trend = "down" if value > 0 else "up"
    else:
        trend = "up" if derivative > 0 else "down"
    percent = float(
        Decimal.from_float(value * 1000).to_integral_value(rounding=ROUND_HALF_EVEN) / 10
    )
    return {
        "value": value,
        "percent": 0.0 if percent == 0 else percent,
        "phase": phase,
        "trend": trend,
    }


def reference_critical(birth: datetime, day: date, tz: ZoneInfo) -> dict[str, Any]:
    start = datetime.combine(day, time.min, tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tz).astimezone(UTC)
    crossings = []
    for cycle, period in PERIODS.items():
        half_us = period * 86400 * 1_000_000 // 2
        first = ceil(Fraction((start - birth) // MICROSECOND, half_us))
        after_last = ceil(Fraction((end - birth) // MICROSECOND, half_us))
        for index in range(first, after_last):
            at = birth + timedelta(microseconds=index * half_us)
            crossings.append({"cycle": cycle, "at": at.isoformat().replace("+00:00", "Z")})
    crossings.sort(key=lambda crossing: (crossing["at"], list(PERIODS).index(crossing["cycle"])))
    level = len({crossing["cycle"] for crossing in crossings})
    return {
        "level": level,
        "kind": ("none", "single", "double", "triple")[level],
        "crossings": crossings,
    }


def test_fixture_has_required_coverage_and_version() -> None:
    assert DATA["schema_version"] == 1
    assert DATA["algorithm_version"] == ALGORITHM_VERSION == "1.0.0"
    assert DATA["rules"]["period_days"] == PERIODS
    assert DATA["comparison"]["value_absolute_tolerance"] == TOLERANCE
    assert len(DATA["vectors"]) == len(VECTORS) >= 200
    assert {vector["input"]["profile"]["timezone"] for vector in VECTORS.values()} >= {
        "UTC",
        "Asia/Yekaterinburg",
        "Europe/Berlin",
        "America/New_York",
        "Australia/Lord_Howe",
        "Pacific/Apia",
    }
    assert {vector["expected"]["critical"]["kind"] for vector in VECTORS.values()} == {
        "none",
        "single",
        "double",
        "triple",
    }
    assert any(vector["input"]["profile"]["birth_time"] is None for vector in VECTORS.values())
    assert any(
        datetime.fromisoformat(vector["input"]["at"]).microsecond for vector in VECTORS.values()
    )
    assert {tag for vector in VECTORS.values() for tag in vector["tags"]} >= {
        "ordinary",
        "phase_boundary",
        "quarter",
        "critical",
        "midnight",
        "dst",
        "leap_day",
        "skipped_date",
    }


@pytest.mark.parametrize("vector", DATA["vectors"], ids=lambda vector: vector["id"])
def test_every_vector_matches_independent_math_and_current_engine(vector: dict[str, Any]) -> None:
    profile = ProfilePatch.model_validate(vector["input"]["profile"])
    assert profile.birth_date is not None
    birth = datetime.combine(profile.birth_date, profile.birth_time or time(12), UTC)
    at = datetime.fromisoformat(vector["input"]["at"])
    assert at >= birth
    tz = ZoneInfo(profile.timezone)
    expected = vector["expected"]
    # Also validate that the exported result retains the HTTP response shape.
    TypeAdapter(BiorhythmSnapshot).validate_python(expected)
    assert expected["algorithm_version"] == ALGORITHM_VERSION
    assert expected["timezone"] == tz.key
    assert expected["at"] == at.isoformat().replace("+00:00", "Z")
    day = at.astimezone(tz).date()
    assert expected["date"] == str(day)
    actual = engine.snapshot(birth, at)
    vectorized = engine.series(birth, [at])
    for cycle, period in PERIODS.items():
        reference = reference_cycle(birth, at, period)
        exported = expected["cycles"][cycle]
        assert exported["value"] == pytest.approx(reference.pop("value"), rel=0, abs=TOLERANCE)
        assert {key: value for key, value in exported.items() if key != "value"} == reference
        state = actual.cycles[cycle]
        assert state.value == pytest.approx(exported["value"], rel=0, abs=TOLERANCE)
        assert vectorized[cycle][0] == state.value
        assert (state.percent, state.phase, state.trend) == (
            exported["percent"],
            exported["phase"],
            exported["trend"],
        )
    critical = reference_critical(birth, day, tz)
    assert expected["critical"] == critical
    assert (
        TypeAdapter(CriticalInfo).dump_python(engine.critical_info(birth, day, tz), mode="json")
        == critical
    )


@pytest.mark.parametrize(
    "control",
    DATA["manual_controls"],
    ids=lambda control: f"{control['vector_id']}-{control['cycle']}",
)
def test_hand_calculated_controls_are_preserved(control: dict[str, Any]) -> None:
    actual = VECTORS[control["vector_id"]]["expected"]["cycles"][control["cycle"]]
    assert actual == control["expected"]


@pytest.mark.parametrize("control", DATA["rounding_controls"])
def test_hand_calculated_rounding_controls(control: dict[str, float]) -> None:
    percent = engine.percent(control["value"])
    assert percent == control["percent"]
    if percent == 0:
        assert copysign(1, percent) == copysign(1, control["percent"]) == 1


def test_dst_fixtures_include_complete_local_hourly_grids() -> None:
    sizes = Counter(
        (vector["expected"]["timezone"], vector["expected"]["date"])
        for vector in VECTORS.values()
        if "dst" in vector["tags"]
    )
    assert sizes == {
        ("Europe/Berlin", "2026-03-29"): 23,
        ("Europe/Berlin", "2026-10-25"): 25,
        ("America/New_York", "2026-03-08"): 23,
        ("America/New_York", "2026-11-01"): 25,
        ("Australia/Lord_Howe", "2026-04-05"): 25,
        ("Australia/Lord_Howe", "2026-10-04"): 24,
    }


def test_committed_fixtures_match_deterministic_generation() -> None:
    for name, content in generator.generated_files().items():
        assert (generator.FIXTURES_DIR / name).read_bytes() == content


@pytest.mark.parametrize("state", ["current", "missing", "corrupt"])
def test_check_mode_does_not_write_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str
) -> None:
    if state != "missing":
        for name, content in generator.generated_files().items():
            (tmp_path / name).write_bytes(content if state == "current" else b"{}")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(generator, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["generate_biorhythm_vectors", "--check"])
    assert generator.main() == (0 if state == "current" else 1)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_openapi_documents_calculation_and_a_valid_manual_example() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/biorhythms/now"]["get"]
    description = operation["description"]
    for rule in (
        ALGORITHM_VERSION,
        "sin(2*pi*t/P)",
        "roundTiesToEven",
        "ONBOARDING_REQUIRED",
        "1e-12",
    ):
        assert rule in description
    example = operation["responses"]["200"]["content"]["application/json"]["examples"][
        "birth_zero"
    ]["value"]
    assert example == VECTORS["birth-zero"]["expected"]
