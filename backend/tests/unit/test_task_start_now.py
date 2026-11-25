from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.planner.constraints import ConstraintError
from app.modules.planner.contracts import Interval, PlanSlot
from app.modules.schedule.adapters import with_started_interval
from app.modules.tasks.placement_schemas import TaskStartNowRequest
from tests.unit.test_planner_replan import at, slot, task


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 0},
        {"schedule_versions": {"2026-11-14": True}},
        {"actual_start": "2026-11-14T08:00:00Z"},
        {"start_at": "2026-11-14T08:00:00Z"},
        {"planned_date": "2026-11-14"},
        {"duration_min": 5},
    ],
)
def test_start_accepts_only_versions_and_rejects_client_time(change: dict) -> None:
    with pytest.raises(ValidationError):
        TaskStartNowRequest.model_validate(
            {"version": 1, "schedule_versions": {"2026-11-14": 0}} | change
        )


@pytest.mark.parametrize("field", ["version", "schedule_versions"])
def test_start_requires_both_version_fields(field: str) -> None:
    body = {"version": 1, "schedule_versions": {"2026-11-14": 0}}
    del body[field]
    with pytest.raises(ValidationError):
        TaskStartNowRequest.model_validate(body)


def test_start_openapi_publishes_versions_security_and_response() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/tasks/{task_id}/start-now"]["post"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    model = schema["components"]["schemas"]["TaskStartNowRequest"]
    assert set(model["required"]) == {"version", "schedule_versions"}
    assert model["additionalProperties"] is False
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskResponse"
    }


def test_started_interval_keeps_saved_slots_immutable_and_drops_only_future_derived_breaks() -> (
    None
):
    item = task()
    old = slot(item, 14)
    other = slot(task(1), 11)
    future_break = PlanSlot("break", Interval(at(9), at(9, 15)))
    past_break = PlanSlot("break", Interval(at(7), at(7, 15)))
    previous = (past_break, future_break, old, other)
    interval = Interval(at(8, 7), at(8, 37))
    result = with_started_interval(previous, replace(item, actual_start=interval.start), interval)
    assert previous == (past_break, future_break, old, other) and old.interval.start == at(14)
    assert past_break in result and other in result and future_break not in result
    selected = next(saved for saved in result if saved.task == item.ref)
    assert selected.interval == interval and selected.preservation == "started"


def test_started_adapter_refuses_to_move_an_already_begun_interval() -> None:
    item = task(actual_start=at(10))
    with pytest.raises(ConstraintError, match="Начатый"):
        with_started_interval((slot(item, 9),), item, Interval(at(10), at(10, 30)))


@pytest.mark.parametrize(
    "change", [{"actual_start": None}, {"status": "done"}, {"duration_min": 60}]
)
def test_started_adapter_requires_matching_task_and_duration(change: dict) -> None:
    item = task(actual_start=at(8))
    with pytest.raises(ConstraintError):
        with_started_interval(
            (), replace(item, **change), Interval(at(8), at(8) + timedelta(minutes=30))
        )
