from app.main import create_app
from app.modules.schedule.read_models import ScheduleReadResult


def test_schedule_get_publishes_required_date_security_and_response() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/schedule"]["get"]
    assert operation["tags"] == ["schedule"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert len(operation["parameters"]) == 1
    parameter = operation["parameters"][0]
    assert (parameter["name"], parameter["in"], parameter["required"]) == ("date", "query", True)
    assert parameter["schema"]["format"] == "date"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ScheduleReadResult"
    }
    response = schema["components"]["schemas"]["ScheduleReadResult"]
    assert set(response["required"]) == set(ScheduleReadResult.model_fields)
    assert response["additionalProperties"] is False
    for status in (401, 403, 404, 409, 422, 500, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


def test_read_route_preserves_onboarding_and_keeps_legacy_get_unchanged() -> None:
    paths = create_app().openapi()["paths"]
    assert "post" in paths["/api/v1/onboarding/preview"]
    assert "post" in paths["/api/v1/onboarding/complete"]
    assert {path for path in paths if path.startswith("/api/v1/schedule")} == {
        "/api/v1/schedule",
        "/api/v1/schedule/details",
        "/api/v1/schedule/check-placement",
        "/api/v1/schedule/replan",
    }
    assert set(paths["/api/v1/schedule"]) == {"get"}
