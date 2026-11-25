from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.tasks.placement_schemas import TaskPinRequest


def payload() -> dict:
    return {
        "planned_date": "2026-11-24",
        "start_at": "2026-11-24T10:07:30+05:00",
        "version": 3,
        "schedule_versions": {"2026-11-24": 7, "2026-11-25": 0},
    }


def test_pin_normalizes_time_without_rounding_or_losing_date_versions() -> None:
    request = TaskPinRequest.model_validate(payload())
    assert request.start_at == datetime(2026, 11, 24, 5, 7, 30, tzinfo=UTC)
    assert request.planned_date == date(2026, 11, 24)
    assert request.schedule_versions == {date(2026, 11, 24): 7, date(2026, 11, 25): 0}


@pytest.mark.parametrize("field", list(payload()))
def test_pin_requires_every_field(field: str) -> None:
    body = payload()
    del body[field]
    with pytest.raises(ValidationError):
        TaskPinRequest.model_validate(body)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 0},
        {"version": "3"},
        {"start_at": "2026-11-24T10:00:00"},
        {"start_at": None},
        {"planned_date": "2026-11-24T00:00:00Z"},
        {"schedule_versions": None},
        {"schedule_versions": {"2026-11-24": True}},
        {"schedule_versions": {"2026-11-24": -1}},
        {"schedule_versions": {"2026-11-24T00:00:00Z": 1}},
        {"end_at": "2026-11-24T11:00:00Z"},
        {"user_id": "owner"},
        {"duration_min": 30},
        {"is_date_locked": True},
    ],
)
def test_pin_rejects_invalid_fields(change: dict) -> None:
    with pytest.raises(ValidationError):
        TaskPinRequest.model_validate(payload() | change)


def test_pin_openapi_publishes_security_versions_and_shared_errors() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/tasks/{task_id}/pin"]["post"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskResponse"
    }
    request = schema["components"]["schemas"]["TaskPinRequest"]
    assert set(request["required"]) == set(payload())
    assert request["additionalProperties"] is False
    for status in (401, 403, 404, 409, 422, 500, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    task = schema["components"]["schemas"]["TaskResponse"]
    assert {"actual_start", "is_date_locked"} <= set(task["required"])
