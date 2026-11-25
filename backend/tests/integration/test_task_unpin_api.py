from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.schemas import TaskResponse
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.integration.test_schedule_planning_api import seed_pending
from tests.integration.test_schedule_read_api import DAY, create_task, get_schedule, snapshot
from tests.integration.test_schedule_read_api import alembic_config as alembic_config
from tests.integration.test_schedule_read_api import auth_api as auth_api
from tests.integration.test_schedule_read_api import engine as engine
from tests.integration.test_schedule_read_api import migrated_url as migrated_url
from tests.integration.test_schedule_read_api import schedule_api as schedule_api
from tests.integration.test_schedule_read_api import tasks_api as tasks_api
from tests.integration.test_task_pin_api import body as pin_body
from tests.integration.test_tasks_api import TasksAPI

pytestmark = pytest.mark.docker


async def pinned(api: TasksAPI) -> tuple[dict, int]:
    task = await create_task(api)
    response = await api.request("POST", f"/{task['id']}/pin", await pin_body(api, task))
    assert response.status_code == 200, response.text
    return response.json(), (await get_schedule(api)).json()["version"]


def path(task: dict, version: int) -> str:
    return f"/{task['id']}/pin?version={task['version']}&schedule_version={version}"


async def test_unpin_returns_task_keeps_it_readable_and_repeats_without_writes(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    response = await api.request("DELETE", path(task, version))
    assert response.status_code == 200, response.text
    unpinned = TaskResponse.model_validate(response.json())
    assert not unpinned.is_pinned and unpinned.pinned_start is None
    assert unpinned.planned_date == DAY and unpinned.version == task["version"] + 1
    assert (await api.request("GET", f"/{task['id']}")).json() == response.json()
    plan = (await get_schedule(api)).json()
    slot = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
    assert not slot["is_pinned"] and plan["version"] == version + 1
    before = await snapshot(api)
    repeated = await api.request("DELETE", path(response.json(), plan["version"]))
    assert repeated.status_code == 200 and repeated.json() == response.json()
    assert await snapshot(api) == before


async def test_unpin_without_plan_is_a_noop_and_does_not_generate_one(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    task = (await api.request("GET", f"/{task_id}")).json()
    before = await snapshot(api)
    response = await api.request("DELETE", path(task, 0))
    assert response.status_code == 200 and response.json() == task
    assert await snapshot(api) == before
    assert (await get_schedule(api)).status_code == 404


@pytest.mark.parametrize("stale", ["task", "schedule"])
async def test_unpin_checks_versions_before_noop_and_does_not_modify_state(
    schedule_api: TasksAPI, stale: str
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    response = await api.request("DELETE", path(task, version))
    assert response.status_code == 200
    current = response.json()
    before = await snapshot(api)
    request = path(task if stale == "task" else current, version)
    refused = await api.request("DELETE", request)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == (
        "TASK_VERSION_CONFLICT" if stale == "task" else "SCHEDULE_VERSION_CONFLICT"
    )
    assert await snapshot(api) == before


async def test_unpin_preserves_started_interval_through_public_api(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task, version = await pinned(api)
    before = (await get_schedule(api)).json()
    old = next(slot for slot in before["slots"] if slot["task_id"] == task["id"])
    now = datetime.fromisoformat(old["start_at"]) + timedelta(minutes=1)
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(now)
    response = await api.request("DELETE", path(task, version))
    assert response.status_code == 200, response.text
    assert response.json()["actual_start"] == task["actual_start"]
    after = (await get_schedule(api)).json()
    saved = next(slot for slot in after["slots"] if slot["task_id"] == task["id"])
    assert not saved["is_pinned"]
    assert (saved["start_at"], saved["end_at"]) == (old["start_at"], old["end_at"])


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?version=1",
        "?schedule_version=1",
        "?version=0&schedule_version=1",
        "?version=1&schedule_version=-1",
        "?version=1&schedule_version=true",
        "?version=1&schedule_version=1.0",
        "?version=1&version=1&schedule_version=1",
        "?version=1&schedule_version=1&schedule_version=1",
        "?version=1&schedule_version=1&date=2026-11-13",
    ],
)
async def test_unpin_rejects_invalid_query_without_writes(
    schedule_api: TasksAPI, query: str
) -> None:
    api = schedule_api
    task, _ = await pinned(api)
    before = await snapshot(api)
    response = await api.request("DELETE", f"/{task['id']}/pin{query}")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]["fields"][0]["field"].startswith("query.")
    assert await snapshot(api) == before


@pytest.mark.parametrize("visibility", ["foreign", "deleted", "missing"])
async def test_unpin_hides_unavailable_tasks_before_version_checks(
    schedule_api: TasksAPI, visibility: str
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    if visibility == "deleted":
        response = await api.request("DELETE", f"/{task['id']}?version={task['version']}")
        assert response.status_code == 204
    elif visibility == "foreign":
        async with AsyncSession(api.auth.engine) as session, session.begin():
            user = User(email=f"{uuid4()}@auth-tests.example.com", password_hash="hash")
            session.add(user)
            await session.flush()
            other = await make_task(session, user, planned_date=DAY)
            task["id"] = str(other.id)
    else:
        task["id"] = str(uuid4())
    before = await snapshot(api)
    response = await api.request("DELETE", path(task, version))
    assert response.status_code == 404 and response.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert response.json()["error"]["details"] == {} and await snapshot(api) == before


@pytest.mark.parametrize("gate", ["bearer", "email", "onboarding"])
async def test_unpin_uses_existing_access_gates(schedule_api: TasksAPI, gate: str) -> None:
    api = schedule_api
    task, version = await pinned(api)
    async with AsyncSession(api.auth.engine) as session, session.begin():
        if gate == "email":
            user = await session.get(User, api.user_id)
            user.is_email_verified = False
        elif gate == "onboarding":
            profile = await session.get(UserProfile, api.user_id)
            profile.onboarding_completed_at = None
    before = await snapshot(api)
    if gate == "bearer":
        response = await api.auth.client.delete(f"/api/v1/tasks{path(task, version)}")
    else:
        response = await api.request("DELETE", path(task, version))
    assert response.status_code == {"bearer": 401, "email": 403, "onboarding": 409}[gate]
    assert response.headers["cache-control"] == "no-store" and await snapshot(api) == before


@pytest.mark.parametrize("failure", ["storage", "calculation"])
async def test_unpin_http_rolls_back_failed_replan(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    before = await snapshot(api)
    if failure == "storage":
        original = ScheduleService._save_plan

        async def fail(self, *args):
            await original(self, *args)
            raise RuntimeError("private storage failure")

        monkeypatch.setattr(ScheduleService, "_save_plan", fail)
    else:

        def fail_calculation(*args):
            raise RuntimeError("private calculation failure")

        monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", fail_calculation)
    response = await api.request("DELETE", path(task, version))
    assert response.status_code == (500 if failure == "storage" else 503)
    assert "private" not in response.text and await snapshot(api) == before
