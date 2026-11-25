from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.service import ScheduleService
from app.modules.tasks.schemas import TaskResponse
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.integration.test_schedule_planning_api import seed_pending
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
from tests.integration.test_tasks_api import TasksAPI

pytestmark = pytest.mark.docker


async def body(api: TasksAPI, task: dict, target: date = DAY) -> dict:
    versions = {}
    for day in sorted({date.fromisoformat(task["planned_date"]), target}):
        plan = await get_schedule(api, day)
        assert plan.status_code in {200, 404}, plan.text
        versions[day.isoformat()] = plan.json()["version"] if plan.status_code == 200 else 0
    return {
        "planned_date": target.isoformat(),
        "start_at": f"{target}T10:07:30+05:00",
        "version": task["version"],
        "schedule_versions": versions,
    }


async def test_pin_http_returns_saved_task_and_fixed_interval_without_rounding(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task)
    response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == 200, response.text
    pinned = TaskResponse.model_validate(response.json())
    assert pinned.is_pinned is True and pinned.pinned_start.isoformat().endswith("05:07:30+00:00")
    assert pinned.is_date_locked is False and pinned.actual_start is None
    assert (await api.request("GET", f"/{task['id']}")).json() == response.json()
    plan = (await get_schedule(api)).json()
    slot = next(item for item in plan["slots"] if item["task_id"] == task["id"])
    assert slot["start_at"].endswith("05:07:30Z") and slot["is_pinned"] is True
    assert datetime.fromisoformat(slot["end_at"]) - datetime.fromisoformat(
        slot["start_at"]
    ) == timedelta(minutes=30)
    before = await snapshot(api)
    repeated = await api.request("POST", f"/{task['id']}/pin", await body(api, response.json()))
    assert repeated.json() == response.json() and await snapshot(api) == before


async def test_pin_http_can_create_first_plan_and_transfer_between_days(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    task = (await api.request("GET", f"/{task_id}")).json()
    pinned = await api.request("POST", f"/{task_id}/pin", await body(api, task))
    assert pinned.status_code == 200, pinned.text
    original = (await get_schedule(api)).json()
    transferred = await api.request(
        "POST", f"/{task_id}/pin", await body(api, pinned.json(), TARGET)
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["planned_date"] == TARGET.isoformat()
    source, target = (await get_schedule(api)).json(), (await get_schedule(api, TARGET)).json()
    assert source["version"] == original["version"] + 1 and target["version"] == 1
    assert not any(slot["task_id"] == task_id for slot in source["slots"])
    assert any(slot["task_id"] == task_id and slot["is_pinned"] for slot in target["slots"])


async def test_pin_reports_ordinary_task_conflict_and_does_not_save(schedule_api: TasksAPI) -> None:
    api = schedule_api
    resident = await create_task(api)
    selected = await create_task(api)
    plan = (await get_schedule(api)).json()
    occupied = next(slot for slot in plan["slots"] if slot["task_id"] == resident["id"])
    request = await body(api, selected)
    request["start_at"] = occupied["start_at"]
    before = await snapshot(api)
    response = await api.request("POST", f"/{selected['id']}/pin", request)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INTERVAL_OCCUPIED"
    assert response.json()["error"]["details"] == {
        "reason_code": "INTERVAL_OCCUPIED",
        "start_at": occupied["start_at"],
        "end_at": occupied["end_at"],
        "kind": "task",
        "conflicting_task_id": resident["id"],
    }
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    ("start", "code", "reason"),
    [
        ("07:00:00", "TASK_MOVE_NOT_ALLOWED", "OUTSIDE_WORK_WINDOW"),
        ("12:10:00", "INTERVAL_OCCUPIED", "INTERVAL_OCCUPIED"),
        ("23:45:00", "TASK_MOVE_NOT_ALLOWED", "OUTSIDE_SELECTED_DATE"),
    ],
)
async def test_pin_reports_work_window_lunch_and_day_boundary(
    schedule_api: TasksAPI, start: str, code: str, reason: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = (await body(api, task)) | {"start_at": f"{DAY}T{start}+05:00"}
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"]["reason_code"] == reason
    if code == "INTERVAL_OCCUPIED":
        assert response.json()["error"]["details"]["kind"] == "lunch"
        assert response.json()["error"]["details"]["conflicting_task_id"] is None
    assert await snapshot(api) == before


async def test_pin_obeys_exact_deadline(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api, deadline=f"{DAY}T09:00:00+05:00")
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", await body(api, task))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["reason_code"] == "DEADLINE_EXCEEDED"
    assert await snapshot(api) == before


@pytest.mark.parametrize("stale", ["task", "source", "target"])
async def test_pin_rejects_stale_versions_without_writes(
    schedule_api: TasksAPI, stale: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task, TARGET)
    if stale == "task":
        request["version"] = task["version"] - 1
    elif stale == "source":
        request["schedule_versions"][DAY.isoformat()] = 0
    else:
        await create_task(api, planned_date=TARGET.isoformat())
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == (
        "TASK_VERSION_CONFLICT" if stale == "task" else "SCHEDULE_VERSION_CONFLICT"
    )
    assert await snapshot(api) == before


@pytest.mark.parametrize("status", ["complete", "skip"])
async def test_pin_rejects_inactive_tasks(schedule_api: TasksAPI, status: str) -> None:
    api = schedule_api
    task = await create_task(api)
    updated = await api.request("POST", f"/{task['id']}/{status}", {"version": task["version"]})
    assert updated.status_code == 200
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", await body(api, updated.json()))
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "TASK_STATUS_CONFLICT"
    )
    assert await snapshot(api) == before


@pytest.mark.parametrize("gate", ["bearer", "email", "onboarding"])
async def test_pin_uses_existing_access_gates(schedule_api: TasksAPI, gate: str) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task)
    async with AsyncSession(api.auth.engine) as session, session.begin():
        if gate == "email":
            user = await session.get(User, api.user_id)
            user.is_email_verified = False
        elif gate == "onboarding":
            profile = await session.get(UserProfile, api.user_id)
            profile.onboarding_completed_at = None
    before = await snapshot(api)
    if gate == "bearer":
        response = await api.auth.client.post(f"/api/v1/tasks/{task['id']}/pin", json=request)
    else:
        response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == {"bearer": 401, "email": 403, "onboarding": 409}[gate]
    assert response.headers["cache-control"] == "no-store"
    assert await snapshot(api) == before


@pytest.mark.parametrize("visibility", ["foreign", "deleted", "missing"])
async def test_pin_hides_unavailable_tasks(schedule_api: TasksAPI, visibility: str) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task)
    if visibility == "deleted":
        assert (
            await api.request("DELETE", f"/{task['id']}?version={task['version']}")
        ).status_code == 204
    elif visibility == "foreign":
        async with AsyncSession(api.auth.engine) as session, session.begin():
            user = User(email=f"{uuid4()}@auth-tests.example.com", password_hash="hash")
            session.add(user)
            await session.flush()
            row = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
            task["id"] = str(row.id)
    else:
        task["id"] = str(uuid4())
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == 404 and response.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert response.json()["error"]["details"] == {} and await snapshot(api) == before


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"start_at": "2026-11-13T10:00:00"},
        {"end_at": "ignored"},
        {"schedule_versions": {}},
        {"schedule_versions": {str(TARGET): 0}},
    ],
)
async def test_pin_rejects_invalid_body_without_changes(
    schedule_api: TasksAPI, change: dict
) -> None:
    api = schedule_api
    task = await create_task(api)
    before = await snapshot(api)
    response = await api.request("POST", f"/{task['id']}/pin", (await body(api, task)) | change)
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]["fields"][0]["field"].startswith("body.")
    assert await snapshot(api) == before


async def test_pin_http_rolls_back_both_days_on_target_storage_failure(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = schedule_api
    task = await create_task(api)
    request = await body(api, task, TARGET)
    original = ScheduleService._save_plan

    async def fail_after_save(self, user_id, plan, trigger):
        result = await original(self, user_id, plan, trigger)
        if plan.day == TARGET:
            raise RuntimeError("private storage failure")
        return result

    before = await snapshot(api)
    monkeypatch.setattr(ScheduleService, "_save_plan", fail_after_save)
    response = await api.request("POST", f"/{task['id']}/pin", request)
    assert response.status_code == 500 and "private" not in response.text
    assert await snapshot(api) == before
