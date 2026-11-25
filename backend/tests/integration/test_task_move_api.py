from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.core.time import FrozenClock
from app.modules.schedule.service import ScheduleService
from app.modules.users.dependencies import get_clock
from tests.integration.test_schedule_read_api import (
    DAY,
    TARGET,
    create_task,
    get_schedule,
    snapshot,
)
from tests.integration.test_schedule_read_api import alembic_config as alembic_config
from tests.integration.test_schedule_read_api import auth_api as auth_api
from tests.integration.test_schedule_read_api import engine as engine
from tests.integration.test_schedule_read_api import migrated_url as migrated_url
from tests.integration.test_schedule_read_api import schedule_api as schedule_api
from tests.integration.test_schedule_read_api import tasks_api as tasks_api
from tests.integration.test_task_pin_api import body
from tests.integration.test_task_unpin_api import pinned
from tests.integration.test_tasks_api import TasksAPI

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("target", [DAY, TARGET])
async def test_move_replaces_pin_saves_exact_time_and_repeats_without_writes(
    schedule_api: TasksAPI, target
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    request = await body(api, task, target)
    request["start_at"] = f"{target}T11:07:30+05:00"
    response = await api.request("POST", f"/{task['id']}/move", request)
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["is_pinned"] is True and moved["planned_date"] == target.isoformat()
    assert moved["pinned_start"] == f"{target}T06:07:30Z"
    assert (await api.request("GET", f"/{task['id']}")).json() == moved
    plan = (await get_schedule(api, target)).json()
    slot = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
    assert slot["is_pinned"] and slot["start_at"] == moved["pinned_start"]
    assert datetime.fromisoformat(slot["end_at"]) - datetime.fromisoformat(
        slot["start_at"]
    ) == timedelta(minutes=30)
    if target != DAY:
        source = (await get_schedule(api)).json()
        assert source["version"] == version + 1
        assert not any(slot["task_id"] == task["id"] for slot in source["slots"])
    before = await snapshot(api)
    repeated = await api.request(
        "POST",
        f"/{task['id']}/move",
        request
        | {"version": moved["version"], "schedule_versions": {target.isoformat(): plan["version"]}},
    )
    assert repeated.status_code == 200 and repeated.json() == moved
    assert await snapshot(api) == before


async def test_move_of_unpinned_task_rejects_an_occupied_target_without_modifying_source(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    selected = await create_task(api)
    resident = await create_task(api, planned_date=TARGET.isoformat())
    target = (await get_schedule(api, TARGET)).json()
    occupied = next(slot for slot in target["slots"] if slot["task_id"] == resident["id"])
    request = await body(api, selected, TARGET)
    request["start_at"] = occupied["start_at"]
    before = await snapshot(api)
    response = await api.request("POST", f"/{selected['id']}/move", request)
    assert response.status_code == 409 and response.json()["error"]["code"] == "INTERVAL_OCCUPIED"
    assert response.json()["error"]["details"]["conflicting_task_id"] == resident["id"]
    assert await snapshot(api) == before


@pytest.mark.parametrize("stale", ["task", "source", "target"])
async def test_move_checks_versions_of_task_and_both_days(
    schedule_api: TasksAPI, stale: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task, TARGET)
    if stale == "task":
        request["version"] -= 1
    elif stale == "source":
        request["schedule_versions"][DAY.isoformat()] = 0
    else:
        await create_task(api, planned_date=TARGET.isoformat())
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/move", request)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "TASK_VERSION_CONFLICT" if stale == "task" else "SCHEDULE_VERSION_CONFLICT"
    )
    assert await snapshot(api) == before


async def test_move_refuses_to_change_a_started_interval(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task, _ = await pinned(api)
    request = await body(api, task, TARGET)
    clock = FrozenClock(datetime.fromisoformat(task["pinned_start"]) + timedelta(minutes=1))
    api.auth.app.dependency_overrides[get_clock] = lambda: clock
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/move", request)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "TASK_MOVE_NOT_ALLOWED"
    )
    assert response.json()["error"]["details"]["reason_code"] == "TASK_STARTED"
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    "change",
    [
        {"start_at": "2026-11-16T10:00:00"},
        {"version": True},
        {"end_at": "ignored"},
        {"schedule_versions": {str(DAY): 1}},
    ],
)
async def test_move_rejects_invalid_body_and_missing_day_versions(
    schedule_api: TasksAPI, change: dict
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = (await body(api, task, TARGET)) | change
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/move", request)
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await snapshot(api) == before


async def test_move_requires_bearer_and_hides_unknown_tasks(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task)
    before = await snapshot(api)
    unauthorized = await api.auth.client.post(f"/api/v1/tasks/{task['id']}/move", json=request)
    assert unauthorized.status_code == 401 and unauthorized.headers["cache-control"] == "no-store"
    missing = await api.request("POST", f"/{uuid4()}/move", request)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert await snapshot(api) == before


@pytest.mark.parametrize("failure", ["storage", "calculation"])
async def test_move_rolls_back_task_and_both_plans_on_failure(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task, TARGET)
    if failure == "storage":
        original = ScheduleService._save_plan

        async def fail_after_target(self, user_id, plan, trigger):
            result = await original(self, user_id, plan, trigger)
            if plan.day == TARGET:
                raise RuntimeError("private storage failure")
            return result

        monkeypatch.setattr(ScheduleService, "_save_plan", fail_after_target)
    else:

        def fail_calculation(*args):
            raise RuntimeError("private calculation failure")

        monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", fail_calculation)
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/move", request)
    assert response.status_code == (500 if failure == "storage" else 503)
    assert "private" not in response.text and await snapshot(api) == before
