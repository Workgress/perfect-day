from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.schedule.planning_schemas import (
    PlacementCheckRequest,
    PlacementCheckResponse,
    ScheduleReplanRequest,
    TaskMoveRecommendation,
    TaskPlacementExplanation,
    UnscheduledTaskExplanation,
)

TASK_ID = UUID(int=1)


def interval_payload() -> dict[str, object]:
    return {
        "task_id": str(TASK_ID),
        "version": 2,
        "planned_date": "2026-11-23",
        "start_at": "2026-11-23T10:00:00+05:00",
        "end_at": "2026-11-23T11:00:00+05:00",
    }


def recommendation_payload() -> dict[str, object]:
    return {
        "task_id": str(TASK_ID),
        "from_date": "2026-11-23",
        "to_date": "2026-11-24",
        "reason_code": "DAY_OVERLOADED",
        "explanation": "На исходной дате нет свободного интервала на 60 минут.",
    }


def test_replan_requires_explicit_permission_to_change_dates() -> None:
    request = ScheduleReplanRequest(planned_date=date(2026, 11, 23))
    assert request.allow_date_change is False
    assert ScheduleReplanRequest.model_validate(
        {"planned_date": "2026-11-23", "allow_date_change": True}
    ).allow_date_change


@pytest.mark.parametrize("permission", [None, 0, 1, "false", "true"])
def test_replan_rejects_ambiguous_permission(permission: object) -> None:
    with pytest.raises(ValidationError):
        ScheduleReplanRequest.model_validate(
            {"planned_date": "2026-11-23", "allow_date_change": permission}
        )


def test_placement_normalizes_offset_and_keeps_local_date() -> None:
    payload = interval_payload()
    payload.update(start_at="2026-11-23T00:00:00+05:00", end_at="2026-11-23T01:00:00+05:00")
    request = PlacementCheckRequest.model_validate(payload)
    assert request.planned_date == date(2026, 11, 23)
    assert request.start_at == datetime(2026, 11, 22, 19, tzinfo=UTC)
    assert request.model_dump(mode="json")["end_at"] == "2026-11-22T20:00:00Z"


@pytest.mark.parametrize(
    "changes",
    [
        {"end_at": "2026-11-23T10:00:00+05:00"},
        {"end_at": "2026-11-23T09:00:00+05:00"},
        {"start_at": "2026-11-23T10:00:00"},
        {"start_at": 1795410000},
        {"planned_date": "2026-11-23T00:00:00Z"},
        {"version": True},
        {"version": 0},
        {"version": "2"},
        {"task_id": "draft-1"},
        {"user_id": str(UUID(int=2))},
    ],
)
def test_placement_rejects_invalid_or_unknown_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PlacementCheckRequest.model_validate({**interval_payload(), **changes})


@pytest.mark.parametrize("allowed", [False, True])
def test_placement_response_requires_consistent_reasons(allowed: bool) -> None:
    refusal = {"code": "INTERVAL_OCCUPIED", "message": "Интервал занят."}
    reasons = [] if allowed else [refusal]
    response = PlacementCheckResponse.model_validate(
        {**interval_payload(), "allowed": allowed, "reasons": reasons}
    )
    assert response.allowed is allowed
    with pytest.raises(ValidationError):
        PlacementCheckResponse.model_validate(
            {**interval_payload(), "allowed": not allowed, "reasons": reasons}
        )


def test_recommendation_serializes_identity_dates_and_reason_separately() -> None:
    payload = recommendation_payload()
    result = TaskMoveRecommendation.model_validate(payload)
    assert result.model_dump(mode="json") == payload
    assert payload == recommendation_payload()


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": None},
        {"from_date": None},
        {"to_date": "2026-11-23"},
        {"to_date": "2026-11-22"},
        {"to_date": "2026-11-24T00:00:00Z"},
        {"explanation": "   "},
        {"reason_code": ""},
        {"reason_code": "Не хватает места"},
        {"automatic": True},
    ],
)
def test_recommendation_rejects_incomplete_or_executable_payload(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TaskMoveRecommendation.model_validate({**recommendation_payload(), **changes})


@pytest.mark.parametrize("field", ["task_id", "from_date", "to_date", "reason_code", "explanation"])
def test_recommendation_requires_all_fields(field: str) -> None:
    payload = recommendation_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        TaskMoveRecommendation.model_validate(payload)


@pytest.mark.parametrize("preservation", [None, "pinned", "started", "past", "done", "system"])
def test_explanation_exposes_existing_preservation_reasons(preservation: str | None) -> None:
    payload = interval_payload()
    del payload["version"]
    result = TaskPlacementExplanation.model_validate(
        {
            **payload,
            "preservation": preservation,
            "reason_codes": ["PINNED_BY_USER"],
            "explanation": "Начало закреплено пользователем.",
        }
    )
    assert result.preservation == preservation


@pytest.mark.parametrize(
    "changes",
    [{"reason_codes": []}, {"explanation": " "}, {"start_at": None}],
)
def test_unscheduled_explanation_requires_reason_and_has_no_time(
    changes: dict[str, object],
) -> None:
    payload = {
        "task_id": str(TASK_ID),
        "planned_date": "2026-11-23",
        "reason_codes": ["NO_FEASIBLE_INTERVAL"],
        "explanation": "На выбранной дате нет подходящего интервала.",
    }
    assert UnscheduledTaskExplanation.model_validate(payload).planned_date == date(2026, 11, 23)
    with pytest.raises(ValidationError):
        UnscheduledTaskExplanation.model_validate({**payload, **changes})
