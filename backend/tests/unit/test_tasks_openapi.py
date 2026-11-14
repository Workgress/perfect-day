from app.main import create_app


def test_task_routes_expose_security_and_shared_errors() -> None:
    schema = create_app().openapi()
    routes = {
        "/api/v1/tasks": {"get": "200", "post": "201"},
        "/api/v1/tasks/{task_id}": {"get": "200", "patch": "200", "delete": "204"},
        "/api/v1/tasks/{task_id}/complete": {"post": "200"},
        "/api/v1/tasks/{task_id}/skip": {"post": "200"},
        "/api/v1/tasks/{task_id}/reopen": {"post": "200"},
    }
    for path, methods in routes.items():
        for method, status in methods.items():
            operation = schema["paths"][path][method]
            assert operation["security"] == [{"OAuth2PasswordBearer": []}]
            assert status in operation["responses"]
            if status == "204":
                assert "content" not in operation["responses"][status]
            for error in (401, 403, 404, 409, 422, 500):
                assert operation["responses"][str(error)]["content"]["application/json"][
                    "schema"
                ] == {"$ref": "#/components/schemas/ErrorResponse"}


def test_task_query_parameters_and_body_schemas_are_documented() -> None:
    schema = create_app().openapi()
    parameters = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/api/v1/tasks"]["get"]["parameters"]
    }
    assert set(parameters) == {"date", "from", "to", "status", "type", "limit", "offset"}
    assert parameters["limit"]["schema"]["default"] == 50
    delete = schema["paths"]["/api/v1/tasks/{task_id}"]["delete"]
    version = next(
        parameter for parameter in delete["parameters"] if parameter["name"] == "version"
    )
    assert version["in"] == "query" and version["required"]
    create = schema["components"]["schemas"]["TaskCreate"]
    assert set(create["required"]) == {"title", "type", "duration_min", "planned_date"}
    assert create["additionalProperties"] is False
    patch = schema["components"]["schemas"]["TaskPatch"]
    assert patch["required"] == ["version"] and "status" not in patch["properties"]
