from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.time import FrozenClock
from app.modules.users.dependencies import get_clock
from tests.integration.test_schedule_planning_api import seed_pending
from tests.integration.test_schedule_read_api import DAY, create_task, get_schedule, snapshot
from tests.integration.test_schedule_read_api import alembic_config as alembic_config
from tests.integration.test_schedule_read_api import auth_api as auth_api
from tests.integration.test_schedule_read_api import engine as engine
from tests.integration.test_schedule_read_api import migrated_url as migrated_url
from tests.integration.test_schedule_read_api import schedule_api as schedule_api
from tests.integration.test_schedule_read_api import tasks_api as tasks_api
from tests.integration.test_task_unpin_api import pinned
from tests.integration.test_tasks_api import TasksAPI

pytestmark = pytest.mark.docker
NOW = datetime(DAY.year, DAY.month, DAY.day, 5, 7, 13, 123456, tzinfo=UTC)


def freeze(api: TasksAPI, instant: datetime) -> None:
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(instant)


@pytest.mark.parametrize("has_plan", [False, True])
async def test_start_records_server_time_full_interval_and_preserves_it_on_repeat(
    schedule_api: TasksAPI, has_plan: bool
) -> None:
    api = schedule_api
    if has_plan:
        task = await create_task(api)
    else:
        task_id = await seed_pending(api)
        task = (await api.request("GET", f"/{task_id}")).json()
    version = 1 if has_plan else 0
    freeze(api, NOW)
    body = {"version": task["version"], "schedule_versions": {str(DAY): version}}
    response = await api.request("POST", f"/{task['id']}/start-now", body)
    assert response.status_code == 200, response.text
    started = response.json()
    assert started["actual_start"] == NOW.isoformat().replace("+00:00", "Z")
    assert not started["is_pinned"] and started["pinned_start"] is None
    plan = (await get_schedule(api)).json()
    slot = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
    assert slot["start_at"] == started["actual_start"]
    assert datetime.fromisoformat(slot["end_at"]) - NOW == timedelta(minutes=30)
    freeze(api, NOW + timedelta(days=1))
    before = await snapshot(api)
    repeated = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": started["version"], "schedule_versions": {str(DAY): plan["version"]}},
    )
    assert repeated.status_code == 200 and repeated.json() == started
    assert await snapshot(api) == before
    stale_plan = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": started["version"], "schedule_versions": {str(DAY): plan["version"] - 1}},
    )
    assert stale_plan.status_code == 409
    assert stale_plan.json()["error"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    assert await snapshot(api) == before
    refused = await api.request("POST", f"/{task['id']}/start-now", body)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "TASK_VERSION_CONFLICT"
    assert await snapshot(api) == before


async def test_start_at_the_existing_pin_boundary_records_actual_start(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    freeze(api, datetime.fromisoformat(task["pinned_start"]))
    response = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": task["version"], "schedule_versions": {str(DAY): version}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["actual_start"] == task["pinned_start"]
    assert response.json()["is_pinned"] and response.json()["pinned_start"] == task["pinned_start"]


async def test_start_refuses_to_change_an_already_begun_planned_interval(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    freeze(api, datetime.fromisoformat(task["pinned_start"]) + timedelta(minutes=1))
    before = await snapshot(api)
    response = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": task["version"], "schedule_versions": {str(DAY): version}},
    )
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "TASK_MOVE_NOT_ALLOWED"
    )
    assert response.json()["error"]["details"]["reason_code"] == "TASK_STARTED"
    assert await snapshot(api) == before


async def test_start_rejects_occupied_time_without_recording_actual_start(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    resident, version = await pinned(api)
    task_id = await seed_pending(api)
    freeze(api, datetime.fromisoformat(resident["pinned_start"]) + timedelta(minutes=1))
    before = await snapshot(api)
    response = await api.request(
        "POST", f"/{task_id}/start-now", {"version": 1, "schedule_versions": {str(DAY): version}}
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "INTERVAL_OCCUPIED"
    assert response.json()["error"]["details"]["conflicting_task_id"] == resident["id"]
    assert await snapshot(api) == before


async def test_start_requires_current_local_date(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api)
    before = await snapshot(api)
    response = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": task["version"], "schedule_versions": {str(DAY): 1}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason_code"] == "TASK_DATE_MISMATCH"
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    ("hour", "minute", "reason"),
    [
        (2, 0, "OUTSIDE_WORK_WINDOW"),
        (7, 10, "INTERVAL_OCCUPIED"),
        (12, 50, "OUTSIDE_WORK_WINDOW"),
    ],
)
async def test_start_checks_full_duration_work_window_and_lunch(
    schedule_api: TasksAPI, hour: int, minute: int, reason: str
) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    freeze(api, NOW.replace(hour=hour, minute=minute))
    before = await snapshot(api)
    response = await api.request(
        "POST", f"/{task_id}/start-now", {"version": 1, "schedule_versions": {str(DAY): 0}}
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["reason_code"] == reason
    assert await snapshot(api) == before


@pytest.mark.parametrize("status", ["complete", "skip"])
async def test_start_rejects_inactive_tasks(schedule_api: TasksAPI, status: str) -> None:
    api = schedule_api
    task = await create_task(api)
    current = await api.request("POST", f"/{task['id']}/{status}", {"version": task["version"]})
    assert current.status_code == 200
    plan = (await get_schedule(api)).json()
    freeze(api, NOW)
    before = await snapshot(api)
    response = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": current.json()["version"], "schedule_versions": {str(DAY): plan["version"]}},
    )
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "TASK_STATUS_CONFLICT"
    )
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    "change",
    [
        {"actual_start": "2026-11-13T10:00:00Z"},
        {"version": True},
        {"schedule_versions": {}},
    ],
)
async def test_start_rejects_client_time_and_invalid_versions(
    schedule_api: TasksAPI, change: dict
) -> None:
    api = schedule_api
    task = await create_task(api)
    before = await snapshot(api)
    response = await api.request(
        "POST",
        f"/{task['id']}/start-now",
        {"version": task["version"], "schedule_versions": {str(DAY): 1}} | change,
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await snapshot(api) == before


async def test_start_requires_bearer_and_hides_unknown_task(schedule_api: TasksAPI) -> None:
    api = schedule_api
    body = {"version": 1, "schedule_versions": {str(DAY): 0}}
    before = await snapshot(api)
    response = await api.auth.client.post(f"/api/v1/tasks/{uuid4()}/start-now", json=body)
    assert response.status_code == 401
    missing = await api.request("POST", f"/{uuid4()}/start-now", body)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert await snapshot(api) == before
