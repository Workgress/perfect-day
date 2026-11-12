from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.time import FrozenClock
from app.modules.auth.models import AuthSession
from app.modules.tasks.dependencies import get_task_changed_handler
from app.modules.tasks.events import TaskChanged
from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User
from tests.db.factories import make_task, make_user
from tests.integration.test_auth import AuthAPI
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url

pytestmark = pytest.mark.docker
NOW = datetime(2026, 11, 12, 9, tzinfo=UTC)
BODY = {
    "title": " Отчёт ",
    "type": "intellectual",
    "duration_min": 60,
    "planned_date": "2026-11-12",
}
FAKE_ID = "00000000-0000-0000-0000-000000000001"
ROUTES = [
    ("POST", "", BODY),
    ("GET", "", None),
    ("GET", f"/{FAKE_ID}", None),
    ("PATCH", f"/{FAKE_ID}", {"version": 1, "title": "Правка"}),
    ("DELETE", f"/{FAKE_ID}?version=1", None),
    ("POST", f"/{FAKE_ID}/complete", {"version": 1}),
    ("POST", f"/{FAKE_ID}/skip", {"version": 1}),
    ("POST", f"/{FAKE_ID}/reopen", {"version": 1}),
]


@dataclass
class TasksAPI:
    auth: AuthAPI
    token: str
    user_id: UUID
    events: list[TaskChanged]

    async def request(self, method: str, path: str = "", body: Any = None) -> Response:
        response = await self.auth.client.request(
            method,
            f"/api/v1/tasks{path}",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.headers["cache-control"] == "no-store"
        return response


@pytest.fixture
async def tasks_api(auth_api: AuthAPI) -> AsyncIterator[TasksAPI]:
    assert (await auth_api.register()).status_code == 202
    verified = await auth_api.verify(auth_api.publisher.messages[-1][1])
    assert verified.status_code == 200
    token = verified.json()["access_token"]
    user_id = decode_access_token(token, auth_api.settings).sub
    auth_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    events = []

    async def notify(event: TaskChanged) -> None:
        async with auth_api.engine.connect() as connection:
            assert (
                await connection.scalar(select(Task.version).where(Task.id == event.task_id))
                == event.version
            )
        events.append(event)

    auth_api.app.dependency_overrides[get_task_changed_handler] = lambda: notify
    response = await auth_api.client.patch(
        "/api/v1/me/profile",
        json={"timezone": "Asia/Yekaterinburg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    yield TasksAPI(auth_api, token, user_id, events)


async def test_http_lifecycle_and_serialization(tasks_api: TasksAPI) -> None:
    created = await tasks_api.request("POST", body=BODY | {"deadline": "2026-11-12T18:00:00+05:00"})
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["title"] == "Отчёт" and task["deadline"] == "2026-11-12T13:00:00Z"
    assert task["status"] == "pending" and task["version"] == 1
    assert "user_id" not in task and "deleted_at" not in task
    path = f"/{task['id']}"
    assert (await tasks_api.request("GET", path)).json() == task
    listed = await tasks_api.request(
        "GET", "?from=2026-11-12&to=2026-11-12&type=intellectual&status=pending&limit=1&offset=0"
    )
    assert listed.status_code == 200 and listed.json() == {
        "items": [task],
        "total": 1,
        "limit": 1,
        "offset": 0,
    }
    moved = await tasks_api.request(
        "PATCH", path, {"version": 1, "planned_date": "2026-11-13", "deadline": None}
    )
    assert moved.status_code == 200 and moved.json()["version"] == 2
    assert moved.json()["deadline"] is None and moved.json()["planned_date"] == "2026-11-13"
    done = await tasks_api.request("POST", f"{path}/complete", {"version": 2})
    assert done.status_code == 200 and done.json()["completed_at"] == "2026-11-12T09:00:00Z"
    assert done.json()["status"] == "done" and done.json()["version"] == 3
    reopened = await tasks_api.request("POST", f"{path}/reopen", {"version": 3})
    assert reopened.status_code == 200 and reopened.json()["status"] == "pending"
    skipped = await tasks_api.request("POST", f"{path}/skip", {"version": 4})
    assert skipped.status_code == 200 and skipped.json()["status"] == "skipped"
    deleted = await tasks_api.request("DELETE", f"{path}?version=5")
    assert deleted.status_code == 204 and deleted.content == b""
    assert "content-type" not in deleted.headers
    missing = await tasks_api.request("GET", path)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert (await tasks_api.request("GET")).json()["total"] == 0
    assert len(tasks_api.events) == 6


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_all_routes_require_bearer_even_with_refresh_cookie(
    tasks_api: TasksAPI,
    method: str,
    path: str,
    body: Any,
) -> None:
    response = await tasks_api.auth.client.request(method, f"/api/v1/tasks{path}", json=body)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("state", ["unverified", "inactive", "revoked"])
async def test_routes_keep_existing_authentication_checks(tasks_api: TasksAPI, state: str) -> None:
    async with tasks_api.auth.engine.begin() as connection:
        if state == "revoked":
            statement = (
                update(AuthSession)
                .where(AuthSession.user_id == tasks_api.user_id)
                .values(revoked_at=func.now())
            )
        else:
            values = {"is_email_verified": False} if state == "unverified" else {"is_active": False}
            statement = update(User).where(User.id == tasks_api.user_id).values(**values)
        await connection.execute(statement)
    for method, body in (("GET", None), ("POST", BODY)):
        response = await tasks_api.request(method, body=body)
        assert response.status_code == (403 if state == "unverified" else 401)


@pytest.mark.parametrize(
    "query",
    [
        "limit=10&limit=10",
        "status=done&status=pending",
        "date=2026-11-12&date=2026-11-13",
        "unknown=1",
        "limit=0",
        "offset=-1",
        "date=",
        "date=2026-11-12&from=2026-11-11",
        "from=2026-11-13&to=2026-11-12",
    ],
)
async def test_query_validation_keeps_shared_error_contract(
    tasks_api: TasksAPI, query: str
) -> None:
    response = await tasks_api.request("GET", f"?{query}")
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"][0]["field"].startswith("query")


@pytest.mark.parametrize(
    "query", ["", "?version=0", "?version=1&version=1", "?version=1&unknown=x"]
)
async def test_delete_requires_valid_single_version(tasks_api: TasksAPI, query: str) -> None:
    response = await tasks_api.request("DELETE", f"/{FAKE_ID}{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        BODY | {"duration_min": "60"},
        BODY | {"deadline": "2026-11-12"},
        BODY | {"status": "done"},
        BODY | {"is_pinned": True},
    ],
)
async def test_create_validation_has_body_field_paths(
    tasks_api: TasksAPI, body: dict[str, Any]
) -> None:
    response = await tasks_api.request("POST", body=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"].startswith("body.")
    assert not tasks_api.events


async def test_conflicts_and_invalid_transitions_do_not_overwrite(tasks_api: TasksAPI) -> None:
    task = (await tasks_api.request("POST", body=BODY)).json()
    path = f"/{task['id']}"
    done = await tasks_api.request("POST", f"{path}/complete", {"version": 1})
    assert done.status_code == 200
    stale = await tasks_api.request("PATCH", path, {"version": 1, "title": "Правка"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "TASK_VERSION_CONFLICT"
    invalid = await tasks_api.request("POST", f"{path}/skip", {"version": 2})
    assert invalid.status_code == 409 and invalid.json()["error"]["code"] == "TASK_STATUS_CONFLICT"
    assert (await tasks_api.request("GET", path)).json() == done.json()
    assert len(tasks_api.events) == 2


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"version": 1, "title": "Правка"}),
        ("DELETE", "?version=1", None),
        ("POST", "/complete", {"version": 1}),
        ("POST", "/skip", {"version": 1}),
        ("POST", "/reopen", {"version": 1}),
    ],
)
async def test_foreign_tasks_are_indistinguishable_from_missing(
    tasks_api: TasksAPI,
    method: str,
    suffix: str,
    body: Any,
) -> None:
    async with AsyncSession(tasks_api.auth.engine) as session:
        other = await make_user(session, f"{uuid4()}@auth-tests.example.com")
        task = await make_task(session, other)
        task_id = task.id
        await session.commit()
    response = await tasks_api.request(method, f"/{task_id}{suffix}", body)
    assert response.status_code == 404 and response.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert not tasks_api.events


async def test_http_failure_rolls_back_without_exposing_details(
    tasks_api: TasksAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = TaskRepository.save

    async def fail(repository: TaskRepository, task: Task) -> None:
        await original(repository, task)
        raise RuntimeError("private database details")

    monkeypatch.setattr(TaskRepository, "save", fail)
    response = await tasks_api.request("POST", body=BODY)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private database details" not in response.text
    assert (await tasks_api.request("GET")).json()["total"] == 0 and not tasks_api.events


async def test_first_creation_requires_profile_not_completed_onboarding(auth_api: AuthAPI) -> None:
    assert (await auth_api.register()).status_code == 202
    verified = await auth_api.verify(auth_api.publisher.messages[-1][1])
    headers = {"Authorization": f"Bearer {verified.json()['access_token']}"}
    failed = await auth_api.client.post("/api/v1/tasks", json=BODY, headers=headers)
    assert failed.status_code == 409 and failed.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    assert failed.headers["cache-control"] == "no-store"
    profile = await auth_api.client.patch("/api/v1/me/profile", json={}, headers=headers)
    assert profile.status_code == 200 and profile.json()["onboarding"]["completed_at"] is None
    created = await auth_api.client.post("/api/v1/tasks", json=BODY, headers=headers)
    assert created.status_code == 201


async def test_deadline_and_pinned_conflicts_are_exposed_over_http(tasks_api: TasksAPI) -> None:
    invalid = await tasks_api.request("POST", body=BODY | {"deadline": "2026-11-11T18:00:00Z"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["details"]["fields"][0]["field"] == "body.deadline"
    task = (await tasks_api.request("POST", body=BODY)).json()
    async with tasks_api.auth.engine.begin() as connection:
        await connection.execute(
            update(Task).where(Task.id == UUID(task["id"])).values(is_pinned=True, pinned_start=NOW)
        )
    conflict = await tasks_api.request(
        "PATCH", f"/{task['id']}", {"version": 1, "duration_min": 90}
    )
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "TASK_PINNED"
    assert (await tasks_api.request("GET", f"/{task['id']}")).json()["version"] == 1


async def test_invalid_path_uuid_is_a_private_validation_error(tasks_api: TasksAPI) -> None:
    response = await tasks_api.request("GET", "/invalid-uuid")
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == "path.task_id"
