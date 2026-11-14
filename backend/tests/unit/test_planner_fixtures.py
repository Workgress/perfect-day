import json
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest

from app.main import create_app
from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.planner.documentation import rules
from app.modules.planner.engine import build_schedule
from app.modules.planner.replan import replan_remaining_day
from scripts import generate_planner_cases as generator

DATA = json.loads((generator.FIXTURES_DIR / "planner_cases.json").read_text(encoding="utf-8"))
CASES = {item["id"]: item for item in DATA["cases"]}


def assert_portable(actual: Any, expected: Any) -> None:
    if isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-12, rel=0)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_portable(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected, strict=True):
            assert_portable(a, b)
    else:
        assert actual == expected


def test_fixture_coverage_version_and_reproduction() -> None:
    assert (
        DATA["schema_version"] == 1
        and DATA["algorithm_version"] == ALGORITHM_VERSION == "planner-1.0.1"
    )
    assert len(CASES) == len(DATA["cases"]) >= 20
    tags = {tag for case in CASES.values() for tag in case["tags"]}
    assert {
        "lark",
        "dove",
        "owl",
        "critical",
        "pin",
        "deadline",
        "break",
        "overload",
        "replan",
        "DST",
    } <= tags
    assert DATA["rules"] == rules()
    assert (generator.FIXTURES_DIR / "planner_cases.json").read_bytes() == generator.render(
        generator.document()
    )


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda item: item["id"])
def test_all_published_cases_replay_and_account_for_tasks(case: dict[str, Any]) -> None:
    context = generator.CONTEXT.validate_python(case["input"]["context"])
    previous = case["input"]["previous_slots"]
    if case["entrypoint"] == "build_schedule":
        result = build_schedule(context)
        actual = generator.PLAN.dump_python(result, mode="json")
    else:
        outcome = replan_remaining_day(context, generator.SLOTS.validate_python(previous))
        result = outcome.plan
        actual = generator.REPLAN.dump_python(outcome, mode="json")
    assert_portable(actual, case["expected"])
    represented = [slot.task for slot in result.slots if slot.task]
    represented.extend(item.task for item in result.unscheduled)
    represented.extend(item.task for item in result.moves)
    expected_refs = {
        task.ref
        for task in context.tasks
        if task.status != "skipped" or any(slot.task == task.ref for slot in result.slots)
    }
    assert Counter(represented) == Counter({ref: 1 for ref in expected_refs})


def test_independent_capacity_break_and_boundary_acceptance_values() -> None:
    expected = {
        "single": (1, 0.8, 432),
        "single-minimum": (1, 0.72, 388),
        "double": (2, 0.65, 331),
        "double-minimum": (2, 0.585, 298),
        "triple": (3, 0.5, 240),
    }
    for name, (level, factor, capacity) in expected.items():
        metrics = CASES[f"load-{name}"]["expected"]["metrics"]
        assert (metrics["critical_level"], metrics["load_factor"], metrics["capacity_min"]) == (
            level,
            factor,
            capacity,
        )
    for value in (85, 86):
        warnings = CASES[f"load-threshold-{value}"]["expected"]["warnings"]
        assert any(warning["code"] == "OVERLOAD" for warning in warnings) == (value == 86)
    assert CASES["off-grid-pin"]["expected"]["slots"][0]["interval"]["start"].endswith(
        "14:07:00Z"
    ) or any(
        slot["interval"]["start"].endswith("14:07:00Z")
        for slot in CASES["off-grid-pin"]["expected"]["slots"]
    )
    gap = CASES["preview-dst-gap-long-task"]["expected"]["slots"]
    task = next(slot for slot in gap if slot["task"] is not None)
    interval = (
        generator.PLAN.validate_python(CASES["preview-dst-gap-long-task"]["expected"])
        .slots[0]
        .interval
    )
    assert task["interval"]["start"] == "2026-03-29T01:00:00Z"
    assert interval.end - interval.start == timedelta(minutes=120)


def test_openapi_describes_rules_and_approved_preview_example() -> None:
    schema = create_app().openapi()
    for path in ("/api/v1/onboarding/preview", "/api/v1/onboarding/complete"):
        text = schema["paths"][path]["post"]["description"]
        assert (
            ALGORITHM_VERSION in text
            and "planner_cases.json" in text
            and "PLAN_CAPACITY_EXCEEDED" in text
        )
