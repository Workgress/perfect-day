import pytest
from pydantic import ValidationError
from starlette.datastructures import QueryParams

from app.main import create_app
from app.modules.tasks.placement_schemas import TaskUnpinQuery


@pytest.mark.parametrize("version", [0, 1, 100])
def test_unpin_reads_distinct_task_and_schedule_versions(version: int) -> None:
    query = TaskUnpinQuery.model_validate(QueryParams(f"version=3&schedule_version={version}"))
    assert query.version == 3 and query.schedule_version == version


@pytest.mark.parametrize(
    "query",
    [
        "",
        "version=1",
        "schedule_version=1",
        "version=0&schedule_version=1",
        "version=true&schedule_version=1",
        "version=1&schedule_version=-1",
        "version=1&schedule_version=true",
        "version=1&schedule_version=1.0",
        "version=1&schedule_version=",
        "version=1&version=1&schedule_version=1",
        "version=1&schedule_version=1&schedule_version=1",
        "version=1&schedule_version=1&user_id=other",
    ],
)
def test_unpin_rejects_missing_invalid_duplicate_or_unknown_query_fields(query: str) -> None:
    with pytest.raises(ValidationError):
        TaskUnpinQuery.model_validate(QueryParams(query))


def test_unpin_openapi_publishes_query_versions_and_task_response() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/tasks/{task_id}/pin"]["delete"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]
    assert "requestBody" not in operation
    parameters = {item["name"]: item for item in operation["parameters"] if item["in"] == "query"}
    assert set(parameters) == {"version", "schedule_version"}
    assert all(item["required"] for item in parameters.values())
    assert parameters["version"]["schema"]["minimum"] == 1
    assert parameters["schedule_version"]["schema"]["minimum"] == 0
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TaskResponse"
    }
    assert "204" not in operation["responses"]
    for status in (401, 403, 404, 409, 422, 500, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
