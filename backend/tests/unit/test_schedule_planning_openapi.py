import pytest

from app.main import create_app


@pytest.mark.parametrize(
    ("path", "method", "response"),
    [
        ("details", "get", "SchedulePlanningDetails"),
        ("check-placement", "post", "PlacementCheckResponse"),
        ("replan", "post", "ScheduleReplanResponse"),
    ],
)
def test_planning_routes_publish_security_response_and_shared_errors(
    path: str, method: str, response: str
) -> None:
    schema = create_app().openapi()
    operation = schema["paths"][f"/api/v1/schedule/{path}"][method]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": f"#/components/schemas/{response}"
    }
    for status in (401, 403, 404, 409, 422, 500, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


def test_planning_request_schemas_forbid_unknown_fields_and_default_to_no_date_changes() -> None:
    schema = create_app().openapi()
    models = schema["components"]["schemas"]
    assert models["ScheduleReplanRequest"]["additionalProperties"] is False
    assert models["ScheduleReplanRequest"]["properties"]["allow_date_change"]["default"] is False
    assert models["ScheduleReplanRequest"]["required"] == ["planned_date"]
    assert set(models["PlacementCheckRequest"]["required"]) == {
        "task_id",
        "version",
        "planned_date",
        "start_at",
        "end_at",
    }
    assert models["PlacementCheckRequest"]["additionalProperties"] is False
    assert set(models["TaskMoveRecommendation"]["required"]) == {
        "task_id",
        "from_date",
        "to_date",
        "reason_code",
        "explanation",
    }
    query = schema["paths"]["/api/v1/schedule/details"]["get"]["parameters"]
    assert len(query) == 1 and query[0]["name"] == "date" and query[0]["required"] is True
