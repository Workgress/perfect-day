from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.datastructures import QueryParams

from app.modules.tasks.models import Task, TaskPriority, TaskStatus, TaskType
from app.modules.tasks.schemas import (
    TaskCreate,
    TaskDeleteQuery,
    TaskList,
    TaskListQuery,
    TaskPatch,
    TaskResponse,
    TaskStatusCommand,
)


@pytest.fixture
def task_input() -> dict[str, Any]:
    return {
        "title": "Отчёт",
        "type": "intellectual",
        "duration_min": 60,
        "planned_date": "2026-11-12",
    }


def test_create_trims_title_and_sets_only_input_defaults(task_input: dict[str, Any]) -> None:
    task = TaskCreate.model_validate(task_input | {"title": "  Отчёт\n"})
    assert task.title == "Отчёт"
    assert task.priority is TaskPriority.MEDIUM
    assert task.description is None and task.deadline is None
    assert task.planned_date == date(2026, 11, 12)


@pytest.mark.parametrize("duration", [5, 480])
def test_duration_bounds(task_input: dict[str, Any], duration: int) -> None:
    assert (
        TaskCreate.model_validate(task_input | {"duration_min": duration}).duration_min == duration
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", " \t\n"),
        ("title", "x" * 201),
        ("title", 123),
        ("duration_min", 4),
        ("duration_min", 481),
        ("duration_min", 60.0),
        ("duration_min", "60"),
        ("duration_min", True),
        ("type", "rest"),
        ("priority", "urgent"),
        ("planned_date", "2026-02-30"),
        ("planned_date", "20261112"),
        ("planned_date", "2026-11-12T00:00:00Z"),
        ("planned_date", datetime(2026, 11, 12, tzinfo=UTC)),
        ("planned_date", 1794441600),
        ("deadline", "2026-11-12"),
        ("deadline", "2026-11-12T14:00:00"),
        ("deadline", datetime(2026, 11, 12, 14)),
        ("deadline", 1794488400),
        ("deadline", "1794488400"),
        ("deadline", "2026-11-12T25:00:00Z"),
    ],
)
def test_invalid_create_fields(task_input: dict[str, Any], field: str, value: Any) -> None:
    with pytest.raises(ValidationError) as error:
        TaskCreate.model_validate(task_input | {field: value})
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["title", "type", "priority", "duration_min", "planned_date"])
def test_nonnullable_fields_reject_explicit_null(task_input: dict[str, Any], field: str) -> None:
    for schema, payload in ((TaskCreate, task_input), (TaskPatch, {"version": 1})):
        with pytest.raises(ValidationError):
            schema.model_validate(payload | {field: None})
    schema = TaskPatch.model_json_schema()
    assert '"type": "null"' not in str(schema["properties"][field]).replace("'", '"')


@pytest.mark.parametrize("field", ["title", "type", "duration_min", "planned_date"])
def test_create_requires_fields(task_input: dict[str, Any], field: str) -> None:
    del task_input[field]
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(task_input)


def test_title_limit_is_checked_after_trim(task_input: dict[str, Any]) -> None:
    task = TaskCreate.model_validate(task_input | {"title": " " + "я" * 200 + " "})
    assert task.title == "я" * 200


@pytest.mark.parametrize("value", ["2026-11-12T14:00:00+05:00", "2026-11-12T09:00:00Z"])
def test_deadline_normalizes_to_utc(task_input: dict[str, Any], value: str) -> None:
    task = TaskCreate.model_validate(task_input | {"deadline": value})
    assert task.deadline == datetime(2026, 11, 12, 9, tzinfo=UTC)
    assert task.model_dump(mode="json")["deadline"] == "2026-11-12T09:00:00Z"


def test_patch_distinguishes_omission_and_clearing() -> None:
    assert TaskPatch(version=1, title=" Отчёт ").model_dump(exclude_unset=True) == {
        "version": 1,
        "title": "Отчёт",
    }
    assert TaskPatch(version=1, deadline=None, description=None).model_dump(exclude_unset=True) == {
        "version": 1,
        "deadline": None,
        "description": None,
    }


@pytest.mark.parametrize("payload", [{}, {"version": 1}, {"title": "Отчёт"}])
def test_patch_requires_version_and_changes(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TaskPatch.model_validate(payload)


@pytest.mark.parametrize("version", [0, -1, "1", 1.0, True, None])
def test_body_versions_are_strict_positive_integers(version: Any) -> None:
    for schema, payload in ((TaskPatch, {"title": "Отчёт"}), (TaskStatusCommand, {})):
        with pytest.raises(ValidationError):
            schema.model_validate(payload | {"version": version})


@pytest.mark.parametrize(
    "field",
    ["id", "user_id", "status", "completed_at", "is_pinned", "pinned_start", "preferred_start"],
)
def test_server_owned_fields_cannot_be_written(task_input: dict[str, Any], field: str) -> None:
    for schema, payload in (
        (TaskCreate, task_input),
        (TaskPatch, {"version": 1, "title": "Отчёт"}),
        (TaskStatusCommand, {"version": 1}),
    ):
        with pytest.raises(ValidationError) as error:
            schema.model_validate(payload | {field: None})
        assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "query",
    [
        "date=2026-11-12&from=2026-11-11",
        "date=2026-11-12&to=2026-11-13",
        "from=2026-11-13&to=2026-11-12",
        "date=",
        "type=rest",
        "status=active",
        "limit=0",
        "limit=101",
        "limit=1.0",
        "offset=-1",
        "offset=",
        "limit=true",
        "unknown=value",
        "date=2026-11-12&date=2026-11-13",
        "limit=10&limit=10",
    ],
)
def test_invalid_query_parameters(query: str) -> None:
    with pytest.raises(ValidationError):
        TaskListQuery.model_validate(QueryParams(query))


def test_query_defaults_and_http_integer_parsing() -> None:
    defaults = TaskListQuery()
    assert defaults.limit == 50 and defaults.offset == 0
    query = TaskListQuery.model_validate(
        QueryParams("from=2026-11-12&to=2026-11-12&status=done&type=routine&limit=100&offset=2")
    )
    assert query.from_date == query.to_date == date(2026, 11, 12)
    assert query.status is TaskStatus.DONE and query.type is TaskType.ROUTINE
    assert query.limit == 100 and query.offset == 2


@pytest.mark.parametrize("query", ["date=2026-11-12", "from=2026-11-12", "to=2026-11-12"])
def test_single_date_and_open_ranges(query: str) -> None:
    TaskListQuery.model_validate(QueryParams(query))


@pytest.mark.parametrize("query", ["", "version=0", "version=1.0", "version=1&version=1"])
def test_delete_requires_single_positive_version(query: str) -> None:
    with pytest.raises(ValidationError):
        TaskDeleteQuery.model_validate(QueryParams(query))


def test_status_and_delete_commands_share_version_meaning() -> None:
    assert TaskStatusCommand(version=2).version == 2
    assert TaskDeleteQuery.model_validate(QueryParams("version=2")).version == 2


def test_response_serializes_orm_without_exposing_private_fields(
    task_input: dict[str, Any],
) -> None:
    task = Task(
        **task_input,
        id=uuid4(),
        user_id=uuid4(),
        description=None,
        priority=TaskPriority.MEDIUM,
        deadline=None,
        status=TaskStatus.PENDING,
        completed_at=None,
        version=1,
        created_at=datetime(2026, 11, 12, 9, tzinfo=UTC),
        updated_at=datetime(2026, 11, 12, 9, tzinfo=UTC),
        preferred_start=None,
        is_pinned=False,
        pinned_start=None,
    )
    response = TaskResponse.model_validate(task)
    payload = response.model_dump(mode="json")
    assert "user_id" not in payload and "deleted_at" not in payload
    assert payload["created_at"] == "2026-11-12T09:00:00Z"
    assert payload["planned_date"] == "2026-11-12"
    assert payload["status"] == "pending" and payload["is_pinned"] is False
    assert TaskList(items=[response], total=1, limit=50, offset=0).items == [response]
    del payload["deadline"]
    with pytest.raises(ValidationError):
        TaskResponse.model_validate(payload)
