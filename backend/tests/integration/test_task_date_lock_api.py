from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.schedule.service import ScheduleService
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.integration.test_schedule_planning_api import call, seed_pending
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


def body(task: dict, plan_version: int, locked: bool = True) -> dict:
    return {
        "is_date_locked": locked,
        "version": task["version"],
        "schedule_versions": {task["planned_date"]: plan_version},
    }


@pytest.mark.parametrize("has_plan", [False, True])
async def test_date_lock_returns_current_task_and_replans_without_pinning_time(
    schedule_api: TasksAPI, has_plan: bool
) -> None:
    api = schedule_api
    if has_plan:
        task = await create_task(api)
    else:
        task_id = await seed_pending(api)
        task = (await api.request("GET", f"/{task_id}")).json()
    path = f"/{task['id']}/date-lock"
    version = 1 if has_plan else 0
    response = await api.request("PUT", path, body(task, version))
    assert response.status_code == 200, response.text
    locked = response.json()
    assert locked["is_date_locked"] and not locked["is_pinned"] and locked["pinned_start"] is None
    assert locked["actual_start"] is None and locked["planned_date"] == task["planned_date"]
    assert (await api.request("GET", f"/{task['id']}")).json() == locked
    plan = (await get_schedule(api)).json()
    assert plan["version"] == version + 1
    assert any(slot["task_id"] == task["id"] and not slot["is_pinned"] for slot in plan["slots"])
    before = await snapshot(api)
    repeated = await api.request("PUT", path, body(locked, plan["version"]))
    assert repeated.status_code == 200 and repeated.json() == locked
    assert await snapshot(api) == before
    for stale_task, stale_plan, code in (
        (task, version, "TASK_VERSION_CONFLICT"),
        (locked, version, "SCHEDULE_VERSION_CONFLICT"),
    ):
        refused = await api.request("PUT", path, body(stale_task, stale_plan))
        assert refused.status_code == 409 and refused.json()["error"]["code"] == code
        assert await snapshot(api) == before
    unlocked = await api.request("PUT", path, body(locked, plan["version"], False))
    assert unlocked.status_code == 200 and not unlocked.json()["is_date_locked"]
    assert (await get_schedule(api)).json()["version"] == plan["version"] + 1


async def test_date_lock_false_without_plan_is_a_noop(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    task = (await api.request("GET", f"/{task_id}")).json()
    before = await snapshot(api)
    response = await api.request("PUT", f"/{task_id}/date-lock", body(task, 0, False))
    assert response.status_code == 200 and response.json() == task
    assert await snapshot(api) == before and (await get_schedule(api)).status_code == 404


async def test_date_lock_preserves_pin_and_allows_explicit_move_with_both_days_updated(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task, version = await pinned(api)
    locked = await api.request("PUT", f"/{task['id']}/date-lock", body(task, version))
    assert locked.status_code == 200, locked.text
    task = locked.json()
    assert (
        task["is_pinned"]
        and task["pinned_start"]
        == (
            next(
                slot
                for slot in (await get_schedule(api)).json()["slots"]
                if slot["task_id"] == task["id"]
            )
        )["start_at"]
    )
    target = DAY + timedelta(days=3)
    moved = await api.request(
        "POST",
        f"/{task['id']}/move",
        {
            "planned_date": str(target),
            "start_at": f"{target}T09:07:00+05:00",
            "version": task["version"],
            "schedule_versions": {str(DAY): version + 1, str(target): 0},
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["is_date_locked"] and moved.json()["planned_date"] == str(target)
    source = (await get_schedule(api)).json()
    destination = (await get_schedule(api, target)).json()
    assert source["version"] == version + 2 and destination["version"] == 1
    assert not any(slot["task_id"] == task["id"] for slot in source["slots"])
    assert any(slot["task_id"] == task["id"] for slot in destination["slots"])


async def test_public_date_lock_blocks_automatic_move_and_advice_until_disabled(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    async with AsyncSession(api.auth.engine) as session, session.begin():
        user = await session.get(User, api.user_id)
        profile = await session.get(UserProfile, api.user_id)
        profile.work_days = list(range(1, 8))
        profile.birth_date = DAY - timedelta(days=14)
        profile.birth_at_utc = datetime(
            profile.birth_date.year, profile.birth_date.month, profile.birth_date.day, 7, tzinfo=UTC
        )
        row = await make_task(session, user, planned_date=DAY, duration_min=180)
        task_id = str(row.id)
    task = (await api.request("GET", f"/{task_id}")).json()
    locked = await api.request("PUT", f"/{task_id}/date-lock", body(task, 0))
    assert locked.status_code == 200, locked.text
    task = locked.json()
    details = (await call(api, "GET", f"details?date={DAY}")).json()
    assert not details["recommendations"] and not details["schedule"]["moves"]
    assert details["unscheduled_explanations"][0]["task_id"] == task_id
    assert "DATE_CHANGE_FORBIDDEN" in details["unscheduled_explanations"][0]["reason_codes"]
    blocked = await call(
        api,
        "POST",
        "replan",
        {"planned_date": str(DAY), "schedule_version": 1, "allow_date_change": True},
    )
    assert blocked.status_code == 200, blocked.text
    assert not blocked.json()["schedule"]["moves"] and not blocked.json()["recommendations"]
    assert (await api.request("GET", f"/{task_id}")).json()["planned_date"] == str(DAY)
    unlocked = await api.request("PUT", f"/{task_id}/date-lock", body(task, 2, False))
    assert unlocked.status_code == 200, unlocked.text
    details = (await call(api, "GET", f"details?date={DAY}")).json()
    assert any(item["task_id"] == task_id for item in details["recommendations"])
    allowed = await call(
        api,
        "POST",
        "replan",
        {"planned_date": str(DAY), "schedule_version": 3, "allow_date_change": True},
    )
    assert allowed.status_code == 200, allowed.text
    assert len(allowed.json()["schedule"]["moves"]) == 1
    assert (await api.request("GET", f"/{task_id}")).json()["planned_date"] != str(DAY)


async def test_date_lock_preserves_actual_start_and_started_interval(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    now = datetime(DAY.year, DAY.month, DAY.day, 5, 7, tzinfo=UTC)
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(now)
    started = await api.request(
        "POST", f"/{task_id}/start-now", {"version": 1, "schedule_versions": {str(DAY): 0}}
    )
    assert started.status_code == 200, started.text
    before = (await get_schedule(api)).json()
    old = next(slot for slot in before["slots"] if slot["task_id"] == task_id)
    locked = await api.request("PUT", f"/{task_id}/date-lock", body(started.json(), 1))
    assert locked.status_code == 200, locked.text
    assert locked.json()["actual_start"] == started.json()["actual_start"]
    assert not locked.json()["is_pinned"]
    saved = next(
        slot for slot in (await get_schedule(api)).json()["slots"] if slot["task_id"] == task_id
    )
    assert (saved["start_at"], saved["end_at"]) == (old["start_at"], old["end_at"])


@pytest.mark.parametrize(
    "change",
    [
        {"is_date_locked": "true"},
        {"is_date_locked": 1},
        {"is_date_locked": None},
        {"version": True},
        {"schedule_versions": {}},
        {"schedule_versions": {str(DAY): 1, str(DAY + timedelta(days=1)): 0}},
        {"is_pinned": True},
    ],
)
async def test_date_lock_rejects_invalid_input_without_changes(
    schedule_api: TasksAPI, change: dict
) -> None:
    api = schedule_api
    task = await create_task(api)
    before = await snapshot(api)
    response = await api.request("PUT", f"/{task['id']}/date-lock", body(task, 1) | change)
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await snapshot(api) == before


@pytest.mark.parametrize("visibility", ["foreign", "deleted", "missing"])
async def test_date_lock_hides_unavailable_tasks_before_version_checks(
    schedule_api: TasksAPI, visibility: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    if visibility == "deleted":
        assert (
            await api.request("DELETE", f"/{task['id']}?version={task['version']}")
        ).status_code == 204
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
    response = await api.request("PUT", f"/{task['id']}/date-lock", body(task, 0))
    assert response.status_code == 404 and response.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert response.json()["error"]["details"] == {} and await snapshot(api) == before


@pytest.mark.parametrize("gate", ["bearer", "email", "onboarding"])
async def test_date_lock_uses_existing_access_gates(schedule_api: TasksAPI, gate: str) -> None:
    api = schedule_api
    task = await create_task(api)
    async with AsyncSession(api.auth.engine) as session, session.begin():
        if gate == "email":
            (await session.get(User, api.user_id)).is_email_verified = False
        elif gate == "onboarding":
            (await session.get(UserProfile, api.user_id)).onboarding_completed_at = None
    before = await snapshot(api)
    if gate == "bearer":
        response = await api.auth.client.put(
            f"/api/v1/tasks/{task['id']}/date-lock", json=body(task, 1)
        )
    else:
        response = await api.request("PUT", f"/{task['id']}/date-lock", body(task, 1))
    assert response.status_code == {"bearer": 401, "email": 403, "onboarding": 409}[gate]
    assert response.headers["cache-control"] == "no-store" and await snapshot(api) == before


@pytest.mark.parametrize("failure", ["storage", "calculation"])
async def test_date_lock_http_rolls_back_failed_replan(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = schedule_api
    task = await create_task(api)
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
    response = await api.request("PUT", f"/{task['id']}/date-lock", body(task, 1))
    assert response.status_code == (500 if failure == "storage" else 503)
    assert "private" not in response.text and await snapshot(api) == before
