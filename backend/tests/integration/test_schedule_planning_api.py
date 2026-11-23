import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.planning_schemas import (
    PlacementCheckResponse,
    SchedulePlanningDetails,
    ScheduleReplanResponse,
)
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.integration.test_schedule_read_api import (
    DAY,
    create_task,
    get_schedule,
    prepare,
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


async def call(api: TasksAPI, method: str, path: str, body: Any = None):
    response = await api.auth.client.request(
        method,
        f"/api/v1/schedule/{path}",
        json=body,
        headers={"Authorization": f"Bearer {api.token}"},
    )
    assert response.headers["cache-control"] == "no-store"
    return response


async def seed_pending(api: TasksAPI) -> str:
    async with AsyncSession(api.auth.engine) as session, session.begin():
        user = await session.get(User, api.user_id)
        assert user is not None
        task = await make_task(session, user, planned_date=DAY, type="routine", duration_min=30)
        return str(task.id)


async def test_details_exposes_one_saved_version_without_writes_or_calculation(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = schedule_api
    task = await create_task(api)
    legacy = (await get_schedule(api)).json()
    before = await snapshot(api)
    calculate = AsyncMock(side_effect=AssertionError("Reading must not replan"))
    monkeypatch.setattr(ScheduleService, "replan", calculate)
    first = await call(api, "GET", f"details?date={DAY}")
    second = await call(api, "GET", f"details?date={DAY}")
    assert first.status_code == 200, first.text
    result = SchedulePlanningDetails.model_validate(first.json())
    assert first.json() == second.json() and first.json()["schedule"] == legacy
    assert result.placement_explanations[0].task_id.hex == task["id"].replace("-", "")
    assert result.placement_explanations[0].explanation
    assert result.recommendations == () and result.unscheduled_explanations == ()
    assert await snapshot(api) == before
    calculate.assert_not_awaited()


async def test_details_exposes_unplaced_reason_and_non_executing_recommendation(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    late = datetime(DAY.year, DAY.month, DAY.day, 16, tzinfo=UTC)
    api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(late)
    task = await create_task(api)
    assert task["status"] == "pending" and task["planned_date"] == DAY.isoformat()
    before = await snapshot(api)
    response = await call(api, "GET", f"details?date={DAY}")
    assert response.status_code == 200, response.text
    result = SchedulePlanningDetails.model_validate(response.json())
    advice = result.recommendations[0]
    assert str(advice.task_id) == task["id"] and advice.from_date == DAY and advice.to_date > DAY
    unplaced = result.unscheduled_explanations[0]
    assert str(unplaced.task_id) == task["id"] and "DATE_CHANGE_FORBIDDEN" in unplaced.reason_codes
    assert "без времени" in unplaced.explanation and "30 мин" in unplaced.explanation
    assert not result.schedule.moves and not result.schedule.slots
    assert await snapshot(api) == before


async def test_check_uses_real_task_versions_and_occupancy_without_saving(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    first, second = await create_task(api), await create_task(api)
    first = (await api.request("GET", f"/{first['id']}")).json()
    plan = (await get_schedule(api)).json()
    slots = {slot["task_id"]: slot for slot in plan["slots"] if slot["task_id"]}
    own, occupied = slots[first["id"]], slots[second["id"]]
    body = {
        "task_id": first["id"],
        "version": first["version"],
        "planned_date": DAY.isoformat(),
        "start_at": own["start_at"],
        "end_at": own["end_at"],
    }
    before = await snapshot(api)
    allowed = await call(api, "POST", "check-placement", body)
    assert allowed.status_code == 200, allowed.text
    assert PlacementCheckResponse.model_validate(allowed.json()).allowed
    blocked = await call(
        api,
        "POST",
        "check-placement",
        body | {"start_at": occupied["start_at"], "end_at": occupied["end_at"]},
    )
    assert blocked.status_code == 200, blocked.text
    result = PlacementCheckResponse.model_validate(blocked.json())
    assert not result.allowed
    assert any(str(reason.conflicting_task_id) == second["id"] for reason in result.reasons)
    stale = await call(api, "POST", "check-placement", body | {"version": first["version"] - 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "TASK_VERSION_CONFLICT"
    missing = await call(api, "POST", "check-placement", body | {"task_id": str(uuid4())})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "TASK_NOT_FOUND"
    assert await snapshot(api) == before


async def test_manual_replan_returns_saved_details_and_actual_changes(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    task_id = await seed_pending(api)
    response = await call(
        api, "POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": 0}
    )
    assert response.status_code == 200, response.text
    result = ScheduleReplanResponse.model_validate(response.json())
    assert result.schedule.version == 1 and not result.schedule.moves
    assert len(result.changes) == 1
    change = result.changes[0]
    assert str(change.task_id) == task_id and change.kind == "added"
    assert change.before is None and change.after is not None
    read = await call(api, "GET", f"details?date={DAY}")
    assert read.json() == result.model_dump(mode="json", exclude={"changes"})
    second = await call(
        api,
        "POST",
        "replan",
        {"planned_date": DAY.isoformat(), "schedule_version": result.schedule.version},
    )
    assert second.status_code == 200, second.text
    assert second.json()["schedule"]["version"] == 2 and second.json()["changes"] == []


@pytest.mark.parametrize("existing", [False, True])
async def test_replan_version_conflict_does_not_calculate_or_write(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    api = schedule_api
    if existing:
        await create_task(api)
    current = (await get_schedule(api)).json()["version"] if existing else 0
    expected = 0 if existing else 1
    before = await snapshot(api)
    calculate = Mock(side_effect=AssertionError("Stale plans must be rejected before calculation"))
    monkeypatch.setattr("app.modules.schedule.service.replan_remaining_day", calculate)
    response = await call(
        api, "POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": expected}
    )
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "SCHEDULE_VERSION_CONFLICT",
        "message": "Расписание уже изменено, обновите данные",
        "details": {
            "planned_date": DAY.isoformat(),
            "expected_version": expected,
            "current_version": current,
        },
    }
    calculate.assert_not_called()
    assert await snapshot(api) == before


async def test_concurrent_public_replans_with_same_version_have_one_winner(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    await seed_pending(api)
    body = {"planned_date": DAY.isoformat(), "schedule_version": 0}
    responses = await asyncio.wait_for(
        asyncio.gather(call(api, "POST", "replan", body), call(api, "POST", "replan", body)),
        timeout=15,
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["error"]["details"] == {
        "planned_date": DAY.isoformat(),
        "expected_version": 0,
        "current_version": 1,
    }
    assert (await get_schedule(api)).json()["version"] == 1


@pytest.mark.parametrize("failure", ["storage", "response", "calculation"])
async def test_replan_rolls_back_if_storage_or_response_preparation_fails(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = schedule_api
    await seed_pending(api)
    before = await snapshot(api)
    if failure == "storage":
        save = ScheduleService._save_plan

        async def broken(self, *args):
            await save(self, *args)
            raise RuntimeError("private storage failure")

        monkeypatch.setattr(ScheduleService, "_save_plan", broken)
    elif failure == "response":
        monkeypatch.setattr(
            ScheduleReader,
            "get_details",
            AsyncMock(side_effect=RuntimeError("private response failure")),
        )
    else:
        monkeypatch.setattr(
            "app.modules.schedule.service.replan_remaining_day",
            Mock(side_effect=RuntimeError("private calculation failure")),
        )
    response = await call(
        api, "POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": 0}
    )
    assert response.status_code == (503 if failure == "calculation" else 500)
    assert response.json()["error"]["code"] == (
        "PLANNER_UNAVAILABLE" if failure == "calculation" else "INTERNAL_ERROR"
    )
    assert "private" not in response.text
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    "query", ["", "date=bad", f"date={DAY}&date={DAY}", f"date={DAY}&user_id=ignored"]
)
async def test_details_rejects_invalid_queries(schedule_api: TasksAPI, query: str) -> None:
    before = await snapshot(schedule_api)
    response = await call(schedule_api, "GET", f"details?{query}")
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert await snapshot(schedule_api) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"planned_date": "2026-11-13"},
        {"planned_date": "2026-11-13T00:00:00Z", "schedule_version": 0},
        {"planned_date": "2026-11-13", "schedule_version": 0, "allow_date_change": "false"},
        {"planned_date": "2026-11-13", "schedule_version": 0, "user_id": "ignored"},
        {"planned_date": "2026-11-13", "schedule_version": True},
        {"planned_date": "2026-11-13", "schedule_version": "1"},
        {"planned_date": "2026-11-13", "schedule_version": -1},
    ],
)
async def test_replan_validates_body_before_writes(schedule_api: TasksAPI, body: dict) -> None:
    before = await snapshot(schedule_api)
    response = await call(schedule_api, "POST", "replan", body)
    assert response.status_code == 422
    assert await snapshot(schedule_api) == before


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", f"details?date={DAY}", None),
        ("POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": 0}),
        (
            "POST",
            "check-placement",
            {
                "task_id": str(uuid4()),
                "version": 1,
                "planned_date": DAY.isoformat(),
                "start_at": "2026-11-13T09:00:00Z",
                "end_at": "2026-11-13T09:30:00Z",
            },
        ),
    ],
)
async def test_planning_methods_require_bearer_auth(
    schedule_api: TasksAPI, method: str, path: str, body: Any
) -> None:
    before = await snapshot(schedule_api)
    response = await schedule_api.auth.client.request(method, f"/api/v1/schedule/{path}", json=body)
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    assert response.headers["www-authenticate"] == "Bearer"
    assert await snapshot(schedule_api) == before


async def test_details_and_check_do_not_expose_another_users_data(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api)
    email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await api.auth.register(email=email)).status_code == 202
    token = (await api.auth.verify(api.auth.publisher.messages[-1][1])).json()["access_token"]
    await prepare(api, token)
    headers = {"Authorization": f"Bearer {token}"}
    read = await api.auth.client.get(f"/api/v1/schedule/details?date={DAY}", headers=headers)
    assert read.status_code == 404 and read.json()["error"]["code"] == "SCHEDULE_NOT_FOUND"
    checked = await api.auth.client.post(
        "/api/v1/schedule/check-placement",
        headers=headers,
        json={
            "task_id": task["id"],
            "version": task["version"],
            "planned_date": DAY.isoformat(),
            "start_at": "2026-11-13T09:00:00Z",
            "end_at": "2026-11-13T09:30:00Z",
        },
    )
    assert checked.status_code == 404 and checked.json()["error"]["code"] == "TASK_NOT_FOUND"


async def test_replan_requires_explicit_permission_to_change_task_date(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    async with AsyncSession(api.auth.engine) as session, session.begin():
        user = await session.get(User, api.user_id)
        profile = await session.get(UserProfile, api.user_id)
        assert user is not None and profile is not None
        profile.work_days = list(range(1, 8))
        profile.birth_date = DAY - timedelta(days=14)
        profile.birth_at_utc = datetime(
            profile.birth_date.year, profile.birth_date.month, profile.birth_date.day, 7, tzinfo=UTC
        )
        row = await make_task(session, user, planned_date=DAY, duration_min=180)
        task_id = str(row.id)
    blocked = await call(
        api, "POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": 0}
    )
    assert blocked.status_code == 200, blocked.text
    result = ScheduleReplanResponse.model_validate(blocked.json())
    assert not result.schedule.moves and len(result.unscheduled_explanations) == 1
    assert "DATE_CHANGE_FORBIDDEN" in result.unscheduled_explanations[0].reason_codes
    task = (await api.request("GET", f"/{task_id}")).json()
    assert task["planned_date"] == DAY.isoformat() and task["status"] == "pending"
    allowed = await call(
        api,
        "POST",
        "replan",
        {
            "planned_date": DAY.isoformat(),
            "schedule_version": result.schedule.version,
            "allow_date_change": True,
        },
    )
    assert allowed.status_code == 200, allowed.text
    result = ScheduleReplanResponse.model_validate(allowed.json())
    assert len(result.schedule.moves) == 1 and not result.unscheduled_explanations
    move = result.schedule.moves[0]
    assert str(move.task_id) == task_id and move.from_date == DAY and move.to_date > DAY
    task = (await api.request("GET", f"/{task_id}")).json()
    assert task["planned_date"] == move.to_date.isoformat() and task["status"] == "scheduled"
    target = await call(api, "GET", f"details?date={move.to_date}")
    assert target.status_code == 200, target.text
    assert any(slot["task_id"] == task_id for slot in target.json()["schedule"]["slots"])


async def test_http_replan_preserves_pin_and_early_actual_start(schedule_api: TasksAPI) -> None:
    api = schedule_api
    clock = FrozenClock(datetime(DAY.year, DAY.month, DAY.day, 8, tzinfo=UTC))
    async with AsyncSession(api.auth.engine, expire_on_commit=False) as session, session.begin():
        user = await session.get(User, api.user_id)
        assert user is not None
        pinned = await make_task(
            session,
            user,
            planned_date=DAY,
            duration_min=30,
            is_pinned=True,
            pinned_start=clock.now() + timedelta(hours=1),
        )
        started = await make_task(
            session,
            user,
            planned_date=DAY,
            duration_min=30,
            is_pinned=True,
            pinned_start=clock.now() + timedelta(hours=2),
        )
        initial = await ScheduleService(
            session, FrozenClock(clock.now() - timedelta(hours=1))
        ).replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
        saved = {
            str(slot.task.task_id): slot.interval
            for slot in initial.plan.slots
            if slot.task is not None
        }
        pinned_id, started_id = str(pinned.id), str(started.id)
        started.is_pinned = False
        started.pinned_start = None
        started.actual_start = clock.now()
    api.auth.app.dependency_overrides[get_clock] = lambda: clock
    version = (await get_schedule(api)).json()["version"]
    response = await call(
        api, "POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": version}
    )
    assert response.status_code == 200, response.text
    result = ScheduleReplanResponse.model_validate(response.json())
    exposed = {str(item.task_id): item for item in result.placement_explanations}
    for task_id, preservation in ((pinned_id, "pinned"), (started_id, "started")):
        assert exposed[task_id].preservation == preservation
        assert (exposed[task_id].start_at, exposed[task_id].end_at) == (
            saved[task_id].start,
            saved[task_id].end,
        )
    assert exposed[started_id].reason_codes == ("TASK_STARTED",)
    assert (await call(api, "GET", f"details?date={DAY}")).json() == result.model_dump(
        mode="json", exclude={"changes"}
    )


@pytest.mark.parametrize("gate", ["onboarding", "email"])
async def test_all_planning_methods_use_existing_access_gates(
    schedule_api: TasksAPI, gate: str
) -> None:
    api = schedule_api
    task = await create_task(api)
    async with AsyncSession(api.auth.engine) as session, session.begin():
        if gate == "onboarding":
            profile = await session.get(UserProfile, api.user_id)
            assert profile is not None
            profile.onboarding_completed_at = None
        else:
            user = await session.get(User, api.user_id)
            assert user is not None
            user.is_email_verified = False
    before = await snapshot(api)
    for method, path, body in [
        ("GET", f"details?date={DAY}", None),
        ("POST", "replan", {"planned_date": DAY.isoformat(), "schedule_version": 0}),
        (
            "POST",
            "check-placement",
            {
                "task_id": task["id"],
                "version": task["version"],
                "planned_date": DAY.isoformat(),
                "start_at": "2026-11-13T09:00:00Z",
                "end_at": "2026-11-13T09:30:00Z",
            },
        ),
    ]:
        response = await call(api, method, path, body)
        assert response.status_code == (409 if gate == "onboarding" else 403)
        assert response.json()["error"]["code"] == (
            "ONBOARDING_REQUIRED" if gate == "onboarding" else "EMAIL_NOT_VERIFIED"
        )
    assert await snapshot(api) == before


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"start_at": "2026-11-13T09:00:00"},
        {"end_at": "2026-11-13T09:00:00Z"},
        {"user_id": "ignored"},
    ],
)
async def test_check_validates_body_without_changes(schedule_api: TasksAPI, change: dict) -> None:
    task = await create_task(schedule_api)
    body = {
        "task_id": task["id"],
        "version": task["version"],
        "planned_date": DAY.isoformat(),
        "start_at": "2026-11-13T09:00:00Z",
        "end_at": "2026-11-13T09:30:00Z",
    }
    before = await snapshot(schedule_api)
    response = await call(schedule_api, "POST", "check-placement", body | change)
    assert response.status_code == 422
    assert await snapshot(schedule_api) == before
