import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.tasks.events import TaskChanged
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskListQuery, TaskPatch, TaskResponse
from app.modules.tasks.service import TaskService
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_schedule, make_slot, make_task, make_user

pytestmark = pytest.mark.docker
DAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 9, tzinfo=UTC)
CLOCK = FrozenClock(NOW)
BODY = TaskCreate(title="Отчёт", type="intellectual", duration_min=60, planned_date=DAY)


@pytest.fixture
async def owner(engine: AsyncEngine) -> AsyncIterator[UUID]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await make_user(session, f"{uuid4()}@example.ru")
        user_id = user.id
        session.add(UserProfile(user_id=user_id, timezone="Asia/Yekaterinburg"))
        await session.commit()
    try:
        yield user_id
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))


@pytest.fixture
def events() -> list[TaskChanged]:
    return []


@pytest.fixture
async def service(engine: AsyncEngine, events: list[TaskChanged]) -> AsyncIterator[TaskService]:
    async def notify(event: TaskChanged) -> None:
        events.append(event)

    async with AsyncSession(engine) as session:
        yield TaskService(session, CLOCK, notify)


async def seed_task(engine: AsyncEngine, user_id: UUID, **values: Any) -> UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, user_id)
        assert user is not None
        task = await make_task(session, user, planned_date=DAY, **values)
        task_id = task.id
        await session.commit()
        return task_id


async def stored_task(engine: AsyncEngine, task_id: UUID) -> Task:
    async with AsyncSession(engine) as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


async def test_full_lifecycle(
    service: TaskService, owner: UUID, engine: AsyncEngine, events: list[TaskChanged]
) -> None:
    created = await service.create(owner, BODY)
    assert created.version == 1 and created.status is TaskStatus.PENDING
    assert created.created_at == created.updated_at == NOW
    assert await service.get(owner, created.id) == created
    assert (await service.list(owner, TaskListQuery())).total == 1
    moved = await service.patch(
        owner,
        created.id,
        TaskPatch(version=1, planned_date=DAY + timedelta(days=1), description="Подробности"),
    )
    assert moved.version == 2 and moved.description == "Подробности"
    assert moved.updated_at == NOW
    assert events[-1].old_planned_date == DAY
    assert events[-1].new_planned_date == DAY + timedelta(days=1)
    completed = await service.complete(owner, created.id, 2)
    assert completed.version == 3 and completed.completed_at == NOW
    assert completed.updated_at == NOW
    reopened = await service.reopen(owner, created.id, 3)
    assert reopened.version == 4 and reopened.completed_at is None
    skipped = await service.skip(owner, created.id, 4)
    assert skipped.version == 5 and skipped.status is TaskStatus.SKIPPED
    await service.delete(owner, created.id, 5)
    assert (await service.list(owner, TaskListQuery())).items == []
    stored = await stored_task(engine, created.id)
    assert stored.deleted_at == NOW and stored.version == 6
    for action in (service.get, service.delete):
        with pytest.raises(AppError) as error:
            await action(owner, created.id, *([6] if action == service.delete else []))
        assert error.value.body.code == "TASK_NOT_FOUND"
    assert [event.operation for event in events] == [
        "created",
        "updated",
        "completed",
        "reopened",
        "skipped",
        "deleted",
    ]
    assert events[-1].new_planned_date is None


@pytest.mark.parametrize("operation", ["complete", "skip", "reopen"])
@pytest.mark.parametrize("status", list(TaskStatus))
async def test_status_transitions_and_repeats(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    events: list[TaskChanged],
    operation: str,
    status: TaskStatus,
) -> None:
    old_completed = NOW - timedelta(hours=1) if status is TaskStatus.DONE else None
    task_id = await seed_task(
        engine,
        owner,
        status=status,
        completed_at=old_completed,
        actual_start=NOW - timedelta(hours=2),
        actual_end=NOW - timedelta(hours=1),
    )
    target = {
        "complete": TaskStatus.DONE,
        "skip": TaskStatus.SKIPPED,
        "reopen": TaskStatus.PENDING,
    }[operation]
    invalid = (
        (operation == "complete" and status is TaskStatus.SKIPPED)
        or (operation == "skip" and status is TaskStatus.DONE)
        or (operation == "reopen" and status is TaskStatus.SCHEDULED)
    )
    if invalid:
        with pytest.raises(AppError) as error:
            await getattr(service, operation)(owner, task_id, 1)
        assert error.value.body.code == "TASK_STATUS_CONFLICT"
        assert not events
        assert (await stored_task(engine, task_id)).status is status
        return
    result = await getattr(service, operation)(owner, task_id, 1)
    changed = status is not target
    assert result.status is target and result.version == 1 + changed
    assert len(events) == int(changed)
    expected_completed = (
        (old_completed if not changed else NOW) if target is TaskStatus.DONE else None
    )
    assert result.completed_at == expected_completed
    if operation == "reopen" and changed:
        task = await stored_task(engine, task_id)
        assert task.actual_start is None and task.actual_end is None


@pytest.mark.parametrize("operation", ["patch", "delete", "complete", "skip", "reopen"])
async def test_stale_versions_and_foreign_tasks_do_not_change_data(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    events: list[TaskChanged],
    operation: str,
) -> None:
    task_id = await seed_task(engine, owner)
    for user_id, version, code in (
        (uuid4(), 1, "TASK_NOT_FOUND"),
        (owner, 2, "TASK_VERSION_CONFLICT"),
    ):
        with pytest.raises(AppError) as error:
            if operation == "patch":
                await service.patch(user_id, task_id, TaskPatch(version=version, title="Правка"))
            else:
                await getattr(service, operation)(user_id, task_id, version)
        assert error.value.body.code == code
    assert not events and (await stored_task(engine, task_id)).version == 1


@pytest.mark.parametrize("timezone", [None, "Invalid/Timezone"])
@pytest.mark.parametrize("operation", ["create", "patch", "delete", "complete", "skip", "reopen"])
async def test_writes_require_valid_profile_but_reads_do_not(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    events: list[TaskChanged],
    timezone: str | None,
    operation: str,
) -> None:
    task_id = await seed_task(engine, owner)
    async with engine.begin() as connection:
        statement = (
            delete(UserProfile).where(UserProfile.user_id == owner)
            if timezone is None
            else update(UserProfile).where(UserProfile.user_id == owner).values(timezone=timezone)
        )
        await connection.execute(statement)
    with pytest.raises(AppError) as error:
        if operation == "create":
            await service.create(owner, BODY)
        elif operation == "patch":
            await service.patch(owner, task_id, TaskPatch(version=1, title="Правка"))
        else:
            await getattr(service, operation)(owner, task_id, 1)
    assert error.value.body.code == "PROFILE_INCOMPLETE"
    assert not events
    assert (await service.get(owner, task_id)).version == 1
    assert (await service.list(owner, TaskListQuery())).total == 1


async def test_deadline_validation_uses_local_date_and_merged_patch(
    service: TaskService, owner: UUID, engine: AsyncEngine, events: list[TaskChanged]
) -> None:
    valid = BODY.model_copy(update={"deadline": datetime(2026, 11, 11, 20, tzinfo=UTC)})
    task = await service.create(owner, valid)
    assert task.deadline == valid.deadline
    with pytest.raises(AppError) as error:
        await service.patch(owner, task.id, TaskPatch(version=1, planned_date=date(2026, 11, 13)))
    assert error.value.status_code == 422
    assert error.value.body.details["fields"][0]["field"] == "body.deadline"
    assert (await stored_task(engine, task.id)).planned_date == DAY
    assert len(events) == 1
    moved = await service.patch(
        owner, task.id, TaskPatch(version=1, planned_date=date(2026, 11, 13), deadline=None)
    )
    assert moved.version == 2 and moved.deadline is None
    with pytest.raises(AppError):
        await service.create(
            owner, BODY.model_copy(update={"deadline": datetime(2026, 11, 11, 18, tzinfo=UTC)})
        )
    assert (await service.list(owner, TaskListQuery())).total == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"planned_date": date(2026, 11, 13)},
        {"duration_min": 90},
        {"type": "physical"},
        {"priority": "high"},
        {"deadline": NOW + timedelta(days=1)},
    ],
)
async def test_pinned_task_rejects_placement_changes(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    events: list[TaskChanged],
    patch: dict[str, Any],
) -> None:
    task_id = await seed_task(engine, owner, is_pinned=True, pinned_start=NOW)
    with pytest.raises(AppError) as error:
        await service.patch(owner, task_id, TaskPatch.model_validate({"version": 1} | patch))
    assert error.value.body.code == "TASK_PINNED"
    assert not events and (await stored_task(engine, task_id)).version == 1
    edited = await service.patch(owner, task_id, TaskPatch(version=1, title="Новое имя"))
    assert edited.is_pinned and edited.pinned_start == NOW and edited.version == 2
    assert (await service.complete(owner, task_id, 2)).is_pinned


@pytest.mark.parametrize("status", [TaskStatus.SCHEDULED, TaskStatus.DONE, TaskStatus.SKIPPED])
async def test_editing_placement_only_resets_scheduled_status(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    status: TaskStatus,
) -> None:
    task_id = await seed_task(
        engine, owner, status=status, completed_at=NOW if status is TaskStatus.DONE else None
    )
    renamed = await service.patch(owner, task_id, TaskPatch(version=1, title="Новое имя"))
    assert renamed.status is status
    changed = await service.patch(owner, task_id, TaskPatch(version=2, duration_min=90))
    assert changed.status is (TaskStatus.PENDING if status is TaskStatus.SCHEDULED else status)
    assert changed.version == 3


async def test_noop_does_not_update_versions_timestamps_or_emit_events(
    service: TaskService, owner: UUID, events: list[TaskChanged]
) -> None:
    task = await service.create(owner, BODY)
    same = await service.patch(owner, task.id, TaskPatch(version=1, title=" Отчёт "))
    assert same == task and len(events) == 1
    assert await service.reopen(owner, task.id, 1) == task
    done = await service.complete(owner, task.id, 1)
    service.clock = FrozenClock(NOW + timedelta(days=1))
    assert await service.complete(owner, task.id, 2) == done
    assert len(events) == 2
    with pytest.raises(AppError) as error:
        await service.complete(owner, task.id, 1)
    assert error.value.body.code == "TASK_VERSION_CONFLICT"


async def test_hook_observes_committed_state_in_other_connection(
    engine: AsyncEngine, owner: UUID
) -> None:
    async with AsyncSession(engine) as session:
        observed = []

        async def notify(event: TaskChanged) -> None:
            assert not session.in_transaction()
            task = await stored_task(engine, event.task_id)
            assert task.version == event.version
            assert (
                "version" not in event.changed_fields and "updated_at" not in event.changed_fields
            )
            observed.append(event)

        service = TaskService(session, CLOCK, notify)
        task = await service.create(owner, BODY)
        await service.patch(owner, task.id, TaskPatch(version=1, description="Текст"))
        await service.delete(owner, task.id, 2)
        assert len(observed) == 3 and observed[-1].changed_fields == frozenset({"deleted_at"})


async def test_failed_flush_rolls_back_and_does_not_notify(
    service: TaskService,
    owner: UUID,
    engine: AsyncEngine,
    events: list[TaskChanged],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = await seed_task(engine, owner)
    original = service.repository.save

    async def fail(task: Task) -> None:
        await original(task)
        raise RuntimeError("write failed")

    monkeypatch.setattr(service.repository, "save", fail)
    with pytest.raises(RuntimeError, match="write failed"):
        await service.patch(owner, task_id, TaskPatch(version=1, title="Изменено"))
    stored = await stored_task(engine, task_id)
    assert stored.version == 1 and stored.title == "Отчёт" and not events
    with pytest.raises(RuntimeError):
        await service.create(owner, BODY)
    assert (await service.list(owner, TaskListQuery())).total == 1


@pytest.mark.parametrize(
    "operations", [("patch", "patch"), ("patch", "complete"), ("complete", "complete")]
)
async def test_concurrent_changes_have_one_winner(
    engine: AsyncEngine, owner: UUID, operations: tuple[str, str]
) -> None:
    task_id = await seed_task(engine, owner)
    events = []

    async def change(operation: str, title: str) -> TaskResponse:
        async def notify(event: TaskChanged) -> None:
            events.append(event)

        async with AsyncSession(engine) as session:
            service = TaskService(session, CLOCK, notify)
            if operation == "patch":
                return await service.patch(owner, task_id, TaskPatch(version=1, title=title))
            return await service.complete(owner, task_id, 1)

    results = await asyncio.gather(
        change(operations[0], "Первая правка"),
        change(operations[1], "Вторая правка"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, TaskResponse) for result in results) == 1
    failures = [result for result in results if isinstance(result, AppError)]
    assert len(failures) == 1 and failures[0].body.code == "TASK_VERSION_CONFLICT"
    assert (await stored_task(engine, task_id)).version == 2 and len(events) == 1


@pytest.mark.parametrize(
    ("timezone", "planned_date", "deadline", "valid"),
    [
        ("UTC", DAY, datetime(2026, 11, 11, 23, 30, tzinfo=UTC), False),
        ("America/New_York", DAY, datetime(2026, 11, 12, 3, tzinfo=UTC), False),
        ("Europe/Berlin", date(2026, 3, 29), datetime(2026, 3, 28, 23, 30, tzinfo=UTC), True),
        ("Europe/Berlin", date(2026, 10, 25), datetime(2026, 10, 24, 22, 30, tzinfo=UTC), True),
    ],
)
async def test_deadline_uses_profile_timezone_including_dst(
    engine: AsyncEngine,
    owner: UUID,
    service: TaskService,
    timezone: str,
    planned_date: date,
    deadline: datetime,
    valid: bool,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            update(UserProfile).where(UserProfile.user_id == owner).values(timezone=timezone)
        )
    body = BODY.model_copy(update={"planned_date": planned_date, "deadline": deadline})
    if valid:
        assert (await service.create(owner, body)).deadline == deadline
    else:
        with pytest.raises(AppError) as error:
            await service.create(owner, body)
        assert error.value.status_code == 422


async def test_crud_does_not_modify_schedule(
    service: TaskService, engine: AsyncEngine, owner: UUID
) -> None:
    task = await service.create(owner, BODY)
    async with AsyncSession(engine) as session:
        user = await session.get(User, owner)
        stored = await session.get(Task, task.id)
        assert user is not None and stored is not None
        schedule = await make_schedule(session, user)
        await make_slot(session, schedule, stored)
        await session.commit()

    async def snapshot() -> list[list[Any]]:
        async with engine.connect() as connection:
            return [
                list((await connection.execute(select(model.__table__))).mappings())
                for model in (Schedule, ScheduleSlot)
            ]

    before = await snapshot()
    await service.patch(owner, task.id, TaskPatch(version=1, planned_date=date(2026, 11, 13)))
    await service.complete(owner, task.id, 2)
    await service.delete(owner, task.id, 3)
    assert await snapshot() == before
