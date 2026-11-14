from app.main import create_app

ROUTES = {
    "/api/v1/me": "get",
    "/api/v1/me/profile": "patch",
    "/api/v1/biorhythms/now": "get",
    "/api/v1/biorhythms": "get",
    "/api/v1/biorhythms/critical-days": "get",
    "/api/v1/biorhythms/forecast": "get",
}


def test_private_routes_publish_security_models_and_shared_errors() -> None:
    schema = create_app().openapi()
    for path, method in ROUTES.items():
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        for status in (401, 403, 409, 422):
            assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }

    patch = schema["components"]["schemas"]["ProfilePatch"]
    assert set(patch["properties"]) == {
        "birth_date",
        "birth_time",
        "timezone",
        "chronotype",
        "work_start",
        "work_end",
        "sleep_time",
    }
    assert patch["additionalProperties"] is False
    assert "required" not in patch
    assert set(schema["components"]["schemas"]["ProfileDocument"]["required"]) == {
        "id",
        "email",
        "display_name",
        "profile",
        "onboarding",
    }


def test_query_aliases_and_enums_are_exposed_in_openapi() -> None:
    paths = create_app().openapi()["paths"]
    parameters = {item["name"]: item for item in paths["/api/v1/biorhythms"]["get"]["parameters"]}
    assert set(parameters) == {"from", "to", "step"}
    assert parameters["from"]["required"] and parameters["to"]["required"]
    assert parameters["from"]["schema"]["format"] == "date"
    assert parameters["step"]["schema"]["default"] == "day"
    instant = paths["/api/v1/biorhythms/now"]["get"]["parameters"][0]
    assert instant["name"] == "at" and not instant["required"]
    assert instant["schema"]["anyOf"][0]["format"] == "date-time"
