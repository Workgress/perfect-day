import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.tasks.placement_schemas import TaskDateLockRequest


@pytest.mark.parametrize(
    "change",
    [
        {"is_date_locked": None},
        {"is_date_locked": 0},
        {"is_date_locked": 1},
        {"is_date_locked": "true"},
        {"is_date_locked": "false"},
        {"version": True},
        {"version": 0},
        {"schedule_versions": {"2026-11-14": True}},
        {"schedule_versions": {"2026-11-14": -1}},
        {"pinned_start": "2026-11-14T09:00:00Z"},
        {"planned_date": "2026-11-15"},
    ],
)
def test_date_lock_rejects_coerced_values_and_unrelated_fields(change: dict) -> None:
    with pytest.raises(ValidationError):
        TaskDateLockRequest.model_validate(
            {"is_date_locked": True, "version": 1, "schedule_versions": {"2026-11-14": 0}} | change
        )


@pytest.mark.parametrize("field", ["is_date_locked", "version", "schedule_versions"])
def test_date_lock_requires_setting_and_both_versions(field: str) -> None:
    body = {"is_date_locked": True, "version": 1, "schedule_versions": {"2026-11-14": 0}}
    del body[field]
    with pytest.raises(ValidationError):
        TaskDateLockRequest.model_validate(body)


def test_date_lock_openapi_publishes_put_boolean_and_required_versions() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/tasks/{task_id}/date-lock"]["put"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    model = schema["components"]["schemas"]["TaskDateLockRequest"]
    assert set(model["required"]) == {"is_date_locked", "version", "schedule_versions"}
    assert model["properties"]["is_date_locked"]["type"] == "boolean"
    assert model["additionalProperties"] is False
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskResponse"
    }
