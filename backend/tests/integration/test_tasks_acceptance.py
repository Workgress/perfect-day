import asyncio
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.tasks.dependencies import get_task_changed_handler
from app.modules.tasks.models import Task
from app.modules.tasks.repository import TaskRepository
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User
from tests.db.factories import make_schedule, make_slot, make_task, make_user
from tests.integration.test_tasks_api import BODY, NOW, TasksAPI
from tests.integration.test_tasks_api import alembic_config as alembic_config
from tests.integration.test_tasks_api import auth_api as auth_api
from tests.integration.test_tasks_api import engine as engine
from tests.integration.test_tasks_api import migrated_url as migrated_url
from tests.integration.test_tasks_api import tasks_api as tasks_api

pytestmark = pytest.mark.docker


@pytest.mark.parametrize(
    "operations",
    [
        ("patch", "patch"),
        ("patch", "complete"),
        ("complete", "skip"),
        ("delete", "delete"),
        ("delete", "patch"),
    ],
)
async def test_competing_http_writes_do_not_lose_updates(
    tasks_api: TasksAPI,
    operations: tuple[str, str],
) -> None:
    task = (await tasks_api.request("POST", body=BODY)).json()
    path = f"/{task['id']}"

    async def change(operation: str, title: str) -> Any:
        if operation == "patch":
            return await tasks_api.request("PATCH", path, {"version": 1, "title": title})
        if operation == "delete":
            return await tasks_api.request("DELETE", f"{path}?version=1")
        return await tasks_api.request("POST", f"{path}/{operation}", {"version": 1})

    responses = await asyncio.gather(
        change(operations[0], "Первая правка"), change(operations[1], "Вторая правка")
    )
    winners = [response for response in responses if response.status_code in (200, 204)]
    losers = [response for response in responses if response.status_code in (404, 409)]
    assert len(winners) == len(losers) == 1
    deleted = winners[0].status_code == 204
    assert losers[0].json()["error"]["code"] == (
        "TASK_NOT_FOUND" if deleted else "TASK_VERSION_CONFLICT"
    )
    async with AsyncSession(tasks_api.auth.engine) as session:
        stored = await session.get(Task, UUID(task["id"]))
        assert stored is not None and stored.version == 2
        assert (stored.deleted_at is not None) == deleted
    current = await tasks_api.request("GET", path)
    if deleted:
        assert current.status_code == 404
    else:
        assert current.json() == winners[0].json()
    assert len(tasks_api.events) == 2


async def test_repeated_commands_and_noop_preserve_time_and_events(tasks_api: TasksAPI) -> None:
    task = (await tasks_api.request("POST", body=BODY)).json()
    path = f"/{task['id']}"
    noop = await tasks_api.request("PATCH", path, {"version": 1, "title": " Отчёт "})
    assert noop.status_code == 200 and noop.json() == task
    reopened = await tasks_api.request("POST", f"{path}/reopen", {"version": 1})
    assert reopened.status_code == 200 and reopened.json() == task
    assert len(tasks_api.events) == 1
    done = await tasks_api.request("POST", f"{path}/complete", {"version": 1})
    tasks_api.auth.app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW.replace(hour=10))
    repeated = await tasks_api.request("POST", f"{path}/complete", {"version": 2})
    assert repeated.status_code == 200 and repeated.json() == done.json()
    stale = await tasks_api.request("POST", f"{path}/complete", {"version": 1})
    assert stale.status_code == 409 and len(tasks_api.events) == 2
    await tasks_api.request("POST", f"{path}/reopen", {"version": 2})
    skipped = await tasks_api.request("POST", f"{path}/skip", {"version": 3})
    repeated_skip = await tasks_api.request("POST", f"{path}/skip", {"version": 4})
    assert repeated_skip.status_code == 200 and repeated_skip.json() == skipped.json()
    assert len(tasks_api.events) == 4


async def test_partial_patch_clears_only_explicit_nullable_fields(tasks_api: TasksAPI) -> None:
    task = (
        await tasks_api.request(
            "POST",
            body=BODY
            | {
                "description": "Описание",
                "priority": "high",
                "deadline": "2026-11-12T18:00:00+05:00",
            },
        )
    ).json()
    path = f"/{task['id']}"
    cleared = await tasks_api.request("PATCH", path, {"version": 1, "description": None})
    assert cleared.status_code == 200
    assert cleared.json() == task | {"description": None, "version": 2}
    cleared_deadline = await tasks_api.request("PATCH", path, {"version": 2, "deadline": None})
    assert cleared_deadline.status_code == 200
    assert cleared_deadline.json() == task | {"description": None, "deadline": None, "version": 3}


async def test_invalid_move_is_atomic_and_valid_move_updates_both_days(tasks_api: TasksAPI) -> None:
    task = (
        await tasks_api.request("POST", body=BODY | {"deadline": "2026-11-12T18:00:00+05:00"})
    ).json()
    path = f"/{task['id']}"
    invalid = await tasks_api.request(
        "PATCH", path, {"version": 1, "title": "Новое имя", "planned_date": "2026-11-13"}
    )
    assert invalid.status_code == 422
    assert (await tasks_api.request("GET", path)).json() == task
    assert len(tasks_api.events) == 1
    moved = await tasks_api.request(
        "PATCH",
        path,
        {
            "version": 1,
            "planned_date": "2026-11-13",
            "deadline": "2026-11-13T18:00:00+05:00",
        },
    )
    assert moved.status_code == 200 and moved.json()["version"] == 2
    assert (await tasks_api.request("GET", "?date=2026-11-12")).json()["total"] == 0
    assert (await tasks_api.request("GET", "?date=2026-11-13")).json()["items"] == [moved.json()]
    event = tasks_api.events[-1]
    assert event.old_planned_date == date(2026, 11, 12)
    assert event.new_planned_date == date(2026, 11, 13)
    assert event.changed_fields == frozenset({"planned_date", "deadline"})


@pytest.mark.parametrize("operation", ["patch", "complete", "delete"])
async def test_http_write_failure_rolls_back_existing_task(
    tasks_api: TasksAPI,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    before = (await tasks_api.request("POST", body=BODY)).json()
    path = f"/{before['id']}"
    original = TaskRepository.save

    async def fail(repository: TaskRepository, task: Task) -> None:
        await original(repository, task)
        raise RuntimeError("failure after SQL flush")

    monkeypatch.setattr(TaskRepository, "save", fail)
    if operation == "patch":
        response = await tasks_api.request("PATCH", path, {"version": 1, "title": "Правка"})
    elif operation == "delete":
        response = await tasks_api.request("DELETE", f"{path}?version=1")
    else:
        response = await tasks_api.request("POST", f"{path}/complete", {"version": 1})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert (await tasks_api.request("GET", path)).json() == before
    assert len(tasks_api.events) == 1


async def test_paginated_http_list_excludes_foreign_and_deleted_tasks(tasks_api: TasksAPI) -> None:
    tasks = []
    for index in range(4):
        response = await tasks_api.request("POST", body=BODY | {"title": f"Задача {index}"})
        assert response.status_code == 201
        tasks.append(response.json())
    deleted = await tasks_api.request("DELETE", f"/{tasks[-1]['id']}?version=1")
    assert deleted.status_code == 204
    async with AsyncSession(tasks_api.auth.engine) as session:
        other = await make_user(session, f"{uuid4()}@auth-tests.example.com")
        foreign = await make_task(session, other, planned_date=date(2026, 11, 12))
        foreign_id = str(foreign.id)
        await session.commit()
    expected = sorted(tasks[:-1], key=lambda task: task["id"])
    collected = []
    for offset in (0, 2):
        response = await tasks_api.request("GET", f"?date=2026-11-12&limit=2&offset={offset}")
        assert response.status_code == 200 and response.json()["total"] == 3
        collected.extend(response.json()["items"])
    assert collected == expected
    assert foreign_id not in {task["id"] for task in collected}
    beyond = await tasks_api.request("GET", "?date=2026-11-12&offset=100")
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 3


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"version": 2, "title": "Правка"}),
        ("DELETE", "?version=2", None),
        ("POST", "/complete", {"version": 2}),
        ("POST", "/skip", {"version": 2}),
        ("POST", "/reopen", {"version": 2}),
    ],
)
async def test_deleted_task_is_unavailable_to_every_route(
    tasks_api: TasksAPI,
    method: str,
    suffix: str,
    body: Any,
) -> None:
    task = (await tasks_api.request("POST", body=BODY)).json()
    path = f"/{task['id']}"
    assert (await tasks_api.request("DELETE", f"{path}?version=1")).status_code == 204
    response = await tasks_api.request(method, f"{path}{suffix}", body)
    assert response.status_code == 404 and response.json()["error"]["code"] == "TASK_NOT_FOUND"
    async with AsyncSession(tasks_api.auth.engine) as session:
        stored = await session.get(Task, UUID(task["id"]))
        assert stored is not None and stored.deleted_at == NOW and stored.version == 2
    assert len(tasks_api.events) == 2


async def test_default_handler_keeps_saved_schedules_unchanged(tasks_api: TasksAPI) -> None:
    tasks_api.auth.app.dependency_overrides.pop(get_task_changed_handler)
    task = (await tasks_api.request("POST", body=BODY)).json()
    async with AsyncSession(tasks_api.auth.engine) as session:
        user = await session.get(User, tasks_api.user_id)
        stored = await session.get(Task, UUID(task["id"]))
        assert user is not None and stored is not None
        schedule = await make_schedule(session, user, date=date(2026, 11, 12))
        await make_slot(session, schedule, stored)
        await session.commit()

    async def snapshot() -> list[list[Any]]:
        async with tasks_api.auth.engine.connect() as connection:
            return [
                list((await connection.execute(select(model.__table__))).mappings())
                for model in (Schedule, ScheduleSlot)
            ]

    before = await snapshot()
    path = f"/{task['id']}"
    moved = await tasks_api.request("PATCH", path, {"version": 1, "planned_date": "2026-11-13"})
    assert moved.status_code == 200
    assert (await tasks_api.request("POST", f"{path}/complete", {"version": 2})).status_code == 200
    assert (await tasks_api.request("DELETE", f"{path}?version=3")).status_code == 204
    assert await snapshot() == before
