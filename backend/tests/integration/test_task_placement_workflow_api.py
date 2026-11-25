import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.core.time import FrozenClock
from app.modules.users.dependencies import get_clock
from tests.integration.test_schedule_planning_api import call
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
from tests.integration.test_task_pin_api import body as placement_body
from tests.integration.test_tasks_api import TasksAPI

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("start_pinned", [False, True])
async def test_public_placement_workflow_keeps_versions_dates_and_actual_start_consistent(
    schedule_api: TasksAPI, start_pinned: bool
) -> None:
    api = schedule_api
    now = datetime(DAY.year, DAY.month, DAY.day, 5, 7, 13, 123456, tzinfo=UTC)
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(now)
    task = await create_task(api)
    path = f"/{task['id']}"
    response = await api.request(
        "PUT",
        f"{path}/date-lock",
        {"is_date_locked": True, "version": task["version"], "schedule_versions": {str(DAY): 1}},
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["is_date_locked"] and not task["is_pinned"]
    request = await placement_body(api, task)
    request["start_at"] = f"{DAY}T11:07:30+05:00"
    response = await api.request("POST", f"{path}/pin", request)
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["is_pinned"] and task["is_date_locked"]

    for day in (TARGET, DAY):
        source_day = DAY if day == TARGET else TARGET
        old_source = (await get_schedule(api, source_day)).json()
        destination = await get_schedule(api, day)
        old_destination_version = (
            destination.json()["version"] if destination.status_code == 200 else 0
        )
        request = await placement_body(api, task, day)
        request["start_at"] = f"{day}T11:07:30+05:00"
        response = await api.request("POST", f"{path}/move", request)
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["planned_date"] == str(day) and task["is_date_locked"] and task["is_pinned"]
        source, destination = (
            (await get_schedule(api, source_day)).json(),
            (await get_schedule(api, day)).json(),
        )
        assert source["version"] == old_source["version"] + 1
        assert destination["version"] == old_destination_version + 1
        assert not any(slot["task_id"] == task["id"] for slot in source["slots"])
        assert any(slot["task_id"] == task["id"] for slot in destination["slots"])
        assert (await api.request("GET", path)).json() == task

    plan = (await get_schedule(api)).json()
    if not start_pinned:
        response = await api.request(
            "DELETE", f"{path}/pin?version={task['version']}&schedule_version={plan['version']}"
        )
        assert response.status_code == 200, response.text
        task = response.json()
        plan = (await get_schedule(api)).json()
    start_request = {"version": task["version"], "schedule_versions": {str(DAY): plan["version"]}}
    response = await api.request("POST", f"{path}/start-now", start_request)
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["actual_start"] == now.isoformat().replace("+00:00", "Z")
    assert task["is_pinned"] is start_pinned and task["is_date_locked"]
    plan = (await get_schedule(api)).json()
    started = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
    assert started["start_at"] == task["actual_start"]
    assert datetime.fromisoformat(started["end_at"]) - now == timedelta(minutes=30)
    if start_pinned:
        response = await api.request(
            "DELETE", f"{path}/pin?version={task['version']}&schedule_version={plan['version']}"
        )
        assert response.status_code == 200, response.text
        task = response.json()
        plan = (await get_schedule(api)).json()
    assert not task["is_pinned"] and task["pinned_start"] is None
    assert task["actual_start"] == started["start_at"] and task["is_date_locked"]

    response = await api.request(
        "PUT",
        f"{path}/date-lock",
        {
            "is_date_locked": False,
            "version": task["version"],
            "schedule_versions": {str(DAY): plan["version"]},
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert not task["is_date_locked"] and task["actual_start"] == started["start_at"]
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(now + timedelta(minutes=10))
    for allow_date_change in (False, True):
        old = (await get_schedule(api)).json()
        response = await call(
            api,
            "POST",
            "replan",
            {
                "planned_date": str(DAY),
                "schedule_version": old["version"],
                "allow_date_change": allow_date_change,
            },
        )
        assert response.status_code == 200, response.text
        plan = response.json()["schedule"]
        assert plan["version"] == old["version"] + 1 and not plan["moves"]
        saved = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
        assert (saved["start_at"], saved["end_at"]) == (started["start_at"], started["end_at"])
        assert (await api.request("GET", path)).json() == task

    before = await snapshot(api)
    repeated = await api.request(
        "POST",
        f"{path}/start-now",
        {"version": task["version"], "schedule_versions": {str(DAY): plan["version"]}},
    )
    assert repeated.status_code == 200 and repeated.json() == task
    stale_start = await api.request("POST", f"{path}/start-now", start_request)
    assert (
        stale_start.status_code == 409
        and stale_start.json()["error"]["code"] == "TASK_VERSION_CONFLICT"
    )
    stale_replan = await call(
        api, "POST", "replan", {"planned_date": str(DAY), "schedule_version": plan["version"] - 1}
    )
    assert stale_replan.status_code == 409
    assert stale_replan.json()["error"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    refused_move = await api.request(
        "POST", f"{path}/move", await placement_body(api, task, TARGET)
    )
    assert refused_move.status_code == 409
    assert refused_move.json()["error"]["code"] == "TASK_MOVE_NOT_ALLOWED"
    assert refused_move.json()["error"]["details"]["reason_code"] == "TASK_STARTED"
    assert await snapshot(api) == before


async def test_public_pin_and_manual_replan_with_same_plan_version_have_one_winner(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await placement_body(api, task)
    pin, replan = await asyncio.wait_for(
        asyncio.gather(
            api.request("POST", f"/{task['id']}/pin", request),
            call(api, "POST", "replan", {"planned_date": str(DAY), "schedule_version": 1}),
        ),
        timeout=15,
    )
    assert sorted([pin.status_code, replan.status_code]) == [200, 409]
    conflict = pin if pin.status_code == 409 else replan
    assert conflict.json()["error"]["code"] == "SCHEDULE_VERSION_CONFLICT"
    assert conflict.json()["error"]["details"] == {
        "planned_date": str(DAY),
        "expected_version": 1,
        "current_version": 2,
    }
    current = (await api.request("GET", f"/{task['id']}")).json()
    plan = (await get_schedule(api)).json()
    assert plan["version"] == 2 and current["is_pinned"] is (pin.status_code == 200)
    slot = next(slot for slot in plan["slots"] if slot["task_id"] == task["id"])
    assert slot["is_pinned"] is current["is_pinned"]
    if pin.status_code == 200:
        assert slot["start_at"] == current["pinned_start"]
