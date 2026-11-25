from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.tasks.placement_schemas import TaskMoveRequest, TaskPinRequest
from tests.unit.test_task_pin_schemas import payload


def test_move_and_pin_share_input_semantics_and_preserve_exact_time() -> None:
    body = payload()
    request = TaskMoveRequest.model_validate(body)
    assert request.model_dump() == TaskPinRequest.model_validate(body).model_dump()
    assert request.planned_date == date(2026, 11, 24)
    assert request.start_at == datetime(2026, 11, 24, 5, 7, 30, tzinfo=UTC)


@pytest.mark.parametrize("field", list(payload()))
def test_move_requires_all_fields(field: str) -> None:
    body = payload()
    del body[field]
    with pytest.raises(ValidationError):
        TaskMoveRequest.model_validate(body)


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": "3"},
        {"start_at": "2026-11-24T10:00:00"},
        {"schedule_versions": {"2026-11-24": -1}},
        {"schedule_versions": {"2026-11-24": True}},
        {"end_at": "2026-11-24T11:00:00Z"},
        {"is_pinned": False},
        {"user_id": "other"},
    ],
)
def test_move_rejects_invalid_or_unknown_fields(change: dict) -> None:
    with pytest.raises(ValidationError):
        TaskMoveRequest.model_validate(payload() | change)


def test_move_openapi_publishes_security_request_task_response_and_shared_errors() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/tasks/{task_id}/move"]["post"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskMoveRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskResponse"
    }
    request = schema["components"]["schemas"]["TaskMoveRequest"]
    assert set(request["required"]) == set(payload()) and request["additionalProperties"] is False
    for status in (401, 403, 404, 409, 422, 500, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
