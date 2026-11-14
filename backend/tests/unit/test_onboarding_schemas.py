from datetime import datetime

import pytest
from pydantic import ValidationError

from app.main import create_app
from app.modules.schedule.schemas import OnboardingRequest


def payload() -> dict:
    return {
        "planned_date": "2026-11-14",
        "tasks": [{"title": "  Работа  ", "type": "routine", "duration_min": 17}],
    }


def test_original_title_whitespace_is_retained_for_receipt() -> None:
    assert OnboardingRequest.model_validate(payload()).tasks[0].title == "  Работа  "


@pytest.mark.parametrize("value", [None, True, 5.5, "17", 4, 481])
def test_duration_is_a_strict_integer_in_range(value: object) -> None:
    data = payload()
    data["tasks"][0]["duration_min"] = value
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(data)


@pytest.mark.parametrize("value", [None, 5, "   ", "x" * 201])
def test_titles_are_validated_after_trimming_without_coercion(value: object) -> None:
    data = payload()
    data["tasks"][0]["title"] = value
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(data)


@pytest.mark.parametrize("value", [None, [], [{}] * 101])
def test_task_list_has_one_to_one_hundred_elements(value: object) -> None:
    data = payload()
    data["tasks"] = value
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(data)


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-14T00:00:00Z",
        "2026-11-14T00:00:00",
        1,
        "2026-02-30",
        "14.11.2026",
        datetime(2026, 11, 14),
    ],
)
def test_dates_do_not_accept_datetime_or_timestamp_coercion(value: object) -> None:
    data = payload()
    data["planned_date"] = value
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(data)


@pytest.mark.parametrize("field", ["user_id", "completed", "priority"])
def test_unknown_top_level_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(payload() | {field: True})


@pytest.mark.parametrize("field", ["id", "task_index", "priority", "deadline", "is_pinned"])
def test_initial_tasks_do_not_extend_the_crud_contract(field: str) -> None:
    data = payload()
    data["tasks"][0][field] = True
    with pytest.raises(ValidationError):
        OnboardingRequest.model_validate(data)


def test_openapi_exposes_only_approved_onboarding_operations_with_auth() -> None:
    schema = create_app().openapi()
    for path in ("/api/v1/onboarding/preview", "/api/v1/onboarding/complete"):
        operation = schema["paths"][path]["post"]
        assert (
            operation["security"]
            and "409" in operation["responses"]
            and "503" in operation["responses"]
        )
    parameters = schema["paths"]["/api/v1/onboarding/complete"]["post"]["parameters"]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in parameters)
    # The merged task module owns /tasks; onboarding must not publish a schedule read API.
    assert "/api/v1/schedule" not in schema["paths"]
