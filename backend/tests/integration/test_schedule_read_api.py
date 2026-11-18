from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import Response
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.core.time import FrozenClock
from app.modules.auth.models import AuthSession
from app.modules.planner.contracts import (
    Interval,
    PlanMetrics,
    PlanResult,
    PlanSlot,
    PlanWarning,
    TaskMove,
    TaskRef,
    UnscheduledTask,
)
from app.modules.schedule.models import Schedule, ScheduleSlot, ScheduleTrigger, TaskReplanReceipt
from app.modules.schedule.read_models import ScheduleReadResult
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.dependencies import get_task_changed_handler
from app.modules.tasks.models import Task
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task
from tests.integration.test_tasks_api import NOW, TasksAPI
from tests.integration.test_tasks_api import alembic_config as alembic_config
from tests.integration.test_tasks_api import auth_api as auth_api
from tests.integration.test_tasks_api import engine as engine
from tests.integration.test_tasks_api import migrated_url as migrated_url
from tests.integration.test_tasks_api import tasks_api as tasks_api

pytestmark = pytest.mark.docker
DAY = date(2026, 11, 13)
TARGET = date(2026, 11, 16)


async def prepare(api: TasksAPI, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    profile = await api.auth.client.patch(
        "/api/v1/me/profile",
        json={
            "timezone": "Asia/Yekaterinburg",
            "birth_date": "2026-11-10",
            "birth_time": "12:00:00",
            "chronotype": "dove",
        },
        headers=headers,
    )
    assert profile.status_code == 200, profile.text
    completed = await api.auth.client.post(
        "/api/v1/onboarding/complete",
        json={
            "planned_date": NOW.date().isoformat(),
            "tasks": [{"title": "First task", "type": "routine", "duration_min": 15}],
        },
        headers=headers | {"Idempotency-Key": str(uuid4())},
    )
    assert completed.status_code == 200, completed.text


@pytest.fixture
async def schedule_api(tasks_api: TasksAPI) -> TasksAPI:
    # Exercise production auth, coordinator, reader and persistence, without the CRUD event spy.
    tasks_api.auth.app.dependency_overrides.pop(get_task_changed_handler)
    await prepare(tasks_api, tasks_api.token)
    return tasks_api


async def get_schedule(api: TasksAPI, day: date = DAY, token: str | None = None) -> Response:
    response = await api.auth.client.get(
        "/api/v1/schedule",
        params={"date": day.isoformat()},
        headers={"Authorization": f"Bearer {token or api.token}"},
    )
    assert response.headers["cache-control"] == "no-store"
    if response.status_code == 200:
        assert ScheduleReadResult.model_validate(response.json()).planned_date == day
    return response


async def create_task(api: TasksAPI, **overrides: Any) -> dict[str, Any]:
    response = await api.request(
        "POST",
        body={
            "title": "Read API task",
            "type": "routine",
            "duration_min": 30,
            "planned_date": DAY.isoformat(),
        }
        | overrides,
    )
    assert response.status_code == 201, response.text
    return response.json()


def task_ids(body: dict[str, Any]) -> set[str]:
    return {slot["task_id"] for slot in body["slots"] if slot["kind"] == "task"}


async def snapshot(api: TasksAPI) -> list[list[Any]]:
    async with api.auth.engine.connect() as connection:
        return [
            list(
                (
                    await connection.execute(
                        select(model.__table__).order_by(*model.__table__.primary_key.columns)
                    )
                ).mappings()
            )
            for model in (UserProfile, Task, Schedule, ScheduleSlot, TaskReplanReceipt, AuthSession)
        ]


async def test_crud_updates_are_visible_through_public_schedule_get(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api)
    plan = (await get_schedule(api)).json()
    assert task_ids(plan) == {task["id"]}
    assert plan["metrics"]["planned_min"] == 30
    assert task["status"] == "scheduled"

    path = f"/{task['id']}"
    patched = await api.request("PATCH", path, {"version": task["version"], "duration_min": 45})
    assert patched.status_code == 200, patched.text
    task = patched.json()
    changed = (await get_schedule(api)).json()
    assert changed["version"] > plan["version"] and changed["id"] != plan["id"]
    slot = next(slot for slot in changed["slots"] if slot["task_id"] == task["id"])
    assert datetime.fromisoformat(slot["end_at"]) - datetime.fromisoformat(slot["start_at"]) == (
        timedelta(minutes=45)
    )
    assert changed["metrics"]["planned_min"] == 45

    moved = await api.request(
        "PATCH", path, {"version": task["version"], "planned_date": TARGET.isoformat()}
    )
    assert moved.status_code == 200, moved.text
    task = moved.json()
    assert task_ids((await get_schedule(api)).json()) == set()
    destination = (await get_schedule(api, TARGET)).json()
    assert task_ids(destination) == {task["id"]}

    for command, expected in (
        ("complete", "done"),
        ("reopen", "scheduled"),
        ("skip", "skipped"),
        ("reopen", "scheduled"),
    ):
        response = await api.request("POST", f"{path}/{command}", {"version": task["version"]})
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["status"] == expected
        current = (await get_schedule(api, TARGET)).json()
        assert current["version"] > destination["version"]
        destination = current
        async with AsyncSession(api.auth.engine) as session:
            saved = await ScheduleReader(session).get(api.user_id, TARGET)
            assert saved is not None and saved.model_dump(mode="json") == current

    removed = await api.request("DELETE", f"{path}?version={task['version']}")
    assert removed.status_code == 204 and not removed.content
    final = (await get_schedule(api, TARGET)).json()
    assert final["version"] > destination["version"]
    assert task["id"] not in task_ids(final)


async def test_two_authenticated_users_cannot_read_each_others_schedule(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    owner_task = await create_task(api)
    email = f"{uuid4().hex}@auth-tests.example.com"
    assert (await api.auth.register(email=email)).status_code == 202
    verified = await api.auth.verify(api.auth.publisher.messages[-1][1])
    assert verified.status_code == 200
    other_token = verified.json()["access_token"]
    await prepare(api, other_token)
    missing = await get_schedule(api, token=other_token)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SCHEDULE_NOT_FOUND"

    created = await api.auth.client.post(
        "/api/v1/tasks",
        json={
            "title": "Other user task",
            "type": "routine",
            "duration_min": 20,
            "planned_date": DAY.isoformat(),
        },
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert created.status_code == 201, created.text
    assert task_ids((await get_schedule(api)).json()) == {owner_task["id"]}
    assert task_ids((await get_schedule(api, token=other_token)).json()) == {created.json()["id"]}


async def test_get_only_selects_and_never_calls_replanning(
    schedule_api: TasksAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = schedule_api
    await create_task(api)
    before = await snapshot(api)
    replan = AsyncMock(side_effect=AssertionError("GET must not replan"))
    monkeypatch.setattr(ScheduleService, "replan", replan)
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2].lstrip().split()[0].upper())

    event.listen(api.auth.engine.sync_engine, "before_cursor_execute", record)
    try:
        first = await get_schedule(api)
        second = await get_schedule(api)
        missing = await get_schedule(api, date(2099, 1, 1))
    finally:
        event.remove(api.auth.engine.sync_engine, "before_cursor_execute", record)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert missing.status_code == 404
    assert statements and set(statements) == {"SELECT"}
    assert await snapshot(api) == before
    replan.assert_not_awaited()


@pytest.mark.parametrize("missing_profile", [False, True])
async def test_real_profile_must_have_completed_onboarding(
    tasks_api: TasksAPI, missing_profile: bool
) -> None:
    if missing_profile:
        async with tasks_api.auth.engine.begin() as connection:
            await connection.execute(
                delete(UserProfile).where(UserProfile.user_id == tasks_api.user_id)
            )
    response = await get_schedule(tasks_api)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ONBOARDING_REQUIRED"


@pytest.mark.parametrize(
    ("state", "status", "code"),
    [
        ("missing", 401, "AUTHENTICATION_REQUIRED"),
        ("revoked", 401, "AUTHENTICATION_REQUIRED"),
        ("inactive", 401, "AUTHENTICATION_REQUIRED"),
        ("unverified", 403, "EMAIL_NOT_VERIFIED"),
    ],
)
async def test_real_authentication_blocks_access_to_saved_plan(
    schedule_api: TasksAPI, state: str, status: int, code: str
) -> None:
    api = schedule_api
    if state != "missing":
        claims = decode_access_token(api.token, api.auth.settings)
        async with api.auth.engine.begin() as connection:
            statement = (
                update(AuthSession)
                .where(AuthSession.id == claims.sid)
                .values(revoked_at=datetime.now(UTC))
                if state == "revoked"
                else update(User)
                .where(User.id == api.user_id)
                .values(
                    **(
                        {"is_active": False}
                        if state == "inactive"
                        else {"is_email_verified": False}
                    )
                )
            )
            await connection.execute(statement)
    response = await api.auth.client.get(
        "/api/v1/schedule",
        params={"date": NOW.date().isoformat()},
        headers={} if state == "missing" else {"Authorization": f"Bearer {api.token}"},
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.headers["cache-control"] == "no-store"


async def test_saved_timezone_is_preserved_after_current_profile_changes(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    await create_task(api)
    original = (await get_schedule(api)).json()
    # Change only current profile state, without invoking the profile mutation/replan pipeline.
    async with api.auth.engine.begin() as connection:
        await connection.execute(
            update(UserProfile)
            .where(UserProfile.user_id == api.user_id)
            .values(timezone="America/New_York")
        )
    response = await get_schedule(api)
    assert response.status_code == 200 and response.json() == original
    assert response.json()["timezone"] == "Asia/Yekaterinburg"


async def test_corrupted_saved_result_is_not_hidden_as_empty_or_missing(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    await create_task(api)
    async with AsyncSession(api.auth.engine) as session, session.begin():
        row = await session.scalar(
            select(Schedule).where(
                Schedule.user_id == api.user_id, Schedule.date == DAY, Schedule.is_active.is_(True)
            )
        )
        assert row is not None
        row.summary = {**row.summary, "slot_count": -1}
    response = await get_schedule(api)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCHEDULE_RESULT_INCOMPLETE"


async def test_http_transfers_all_saved_slot_kinds_reasons_warnings_and_moves(
    schedule_api: TasksAPI,
) -> None:
    api = schedule_api
    async with AsyncSession(api.auth.engine) as session, session.begin():
        user = await session.get(User, api.user_id)
        assert user is not None
        placed = await make_task(session, user, planned_date=DAY, duration_min=30)
        unscheduled = await make_task(session, user, planned_date=DAY, duration_min=30)
        moved = await make_task(session, user, planned_date=TARGET, duration_min=30)

        def interval(hour: int, minutes: int) -> Interval:
            start = datetime(2026, 11, 13, hour, tzinfo=UTC)
            return Interval(start, start + timedelta(minutes=minutes))

        target = PlanResult(
            TARGET, "Asia/Yekaterinburg", "planner-1.0.1", (), (), PlanMetrics(0, 0, 300, 0, 0, 1.0)
        )
        plan = PlanResult(
            DAY,
            "Asia/Yekaterinburg",
            "planner-1.0.1",
            (
                PlanSlot(
                    "task",
                    interval(3, 30),
                    TaskRef(task_id=placed.id),
                    reason_codes=("PINNED_BY_USER",),
                    is_pinned=True,
                    explanation="Saved task explanation",
                ),
                PlanSlot("break", interval(4, 15), explanation="Break"),
                PlanSlot("lunch", interval(7, 60), explanation="Lunch"),
                PlanSlot("rest", interval(9, 30), explanation=None),
            ),
            (UnscheduledTask(TaskRef(task_id=unscheduled.id), ("DAY_CAPACITY_EXCEEDED",)),),
            PlanMetrics(90, 30, 300, 30, 2, 0.65, 30),
            moves=(TaskMove(TaskRef(task_id=moved.id), DAY, TARGET, "MOVED_FROM_CRITICAL_DAY"),),
            warnings=(
                PlanWarning(
                    "OVERLOAD", TaskRef(task_id=unscheduled.id), TARGET, "Saved warning", "warning"
                ),
            ),
            future_plans=(target,),
        )
        scheduler = ScheduleService(session, FrozenClock(NOW))
        target_row = await scheduler._save_plan(api.user_id, target, ScheduleTrigger.INITIAL)
        row = await scheduler._save_plan(api.user_id, plan, ScheduleTrigger.INITIAL)
        row.summary = {**row.summary, "future_schedule_ids": [str(target_row.id)]}
        placed_id, unscheduled_id, moved_id = map(str, (placed.id, unscheduled.id, moved.id))

    response = await get_schedule(api)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {slot["kind"] for slot in body["slots"]} == {"task", "break", "lunch", "rest"}
    assert task_ids(body) == {placed_id}
    assert body["slots"][0]["is_pinned"] is True
    assert body["slots"][0]["reason_codes"] == ["PINNED_BY_USER"]
    assert body["unscheduled"] == [
        {"task_id": unscheduled_id, "reason_codes": ["DAY_CAPACITY_EXCEEDED"]}
    ]
    assert body["moves"][0]["task_id"] == moved_id
    assert body["warnings"][0]["target_date"] == TARGET.isoformat()
    assert body["metrics"]["moved_min"] == 30
    async with AsyncSession(api.auth.engine) as session:
        saved = await ScheduleReader(session).get(api.user_id, DAY)
        assert saved is not None and saved.model_dump(mode="json") == body
    assert (await get_schedule(api, TARGET)).status_code == 200


async def test_dst_fold_keeps_distinct_utc_instants(schedule_api: TasksAPI) -> None:
    api = schedule_api
    day = date(2026, 10, 25)
    plan = PlanResult(
        day,
        "Europe/Berlin",
        "planner-1.0.1",
        (
            PlanSlot(
                "rest",
                Interval(
                    datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                    datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                ),
            ),
        ),
        (),
        PlanMetrics(0, 0, 0, 0, 0, 1.0),
    )
    async with AsyncSession(api.auth.engine) as session, session.begin():
        await ScheduleService(session, FrozenClock(NOW))._save_plan(
            api.user_id, plan, ScheduleTrigger.INITIAL
        )
    response = await get_schedule(api, day)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Europe/Berlin"
    assert body["slots"][0]["start_at"] == "2026-10-25T00:30:00Z"
    assert body["slots"][0]["end_at"] == "2026-10-25T01:30:00Z"


async def test_content_edit_noop_and_conflict_keep_schedule_version(schedule_api: TasksAPI) -> None:
    api = schedule_api
    task = await create_task(api)
    original = (await get_schedule(api)).json()
    renamed = await api.request(
        "PATCH", f"/{task['id']}", {"version": task["version"], "title": "New title"}
    )
    assert renamed.status_code == 200, renamed.text
    version = renamed.json()["version"]
    for sent_version, status in ((version, 200), (task["version"], 409)):
        response = await api.request(
            "PATCH", f"/{task['id']}", {"version": sent_version, "title": "New title"}
        )
        assert response.status_code == status, response.text
        if status == 409:
            assert response.json()["error"]["code"] == "TASK_VERSION_CONFLICT"
        assert (await get_schedule(api)).json() == original
