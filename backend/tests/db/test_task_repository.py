from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.tasks.models import Task, TaskPriority, TaskStatus, TaskType
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskListQuery
from app.modules.users.models import User
from tests.db.factories import make_task, make_user

pytestmark = pytest.mark.docker
DAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 9, tzinfo=UTC)


@pytest.fixture
async def catalog(session: AsyncSession) -> tuple[UUID, dict[str, Task]]:
    owner = await make_user(session)
    other = await make_user(session, "other@example.ru")
    tasks = {}
    for index, (name, day, task_type, status) in enumerate(
        [
            ("before", DAY - timedelta(days=1), TaskType.ROUTINE, TaskStatus.PENDING),
            ("first", DAY, TaskType.INTELLECTUAL, TaskStatus.PENDING),
            ("second", DAY, TaskType.PHYSICAL, TaskStatus.DONE),
            ("third", DAY, TaskType.PHYSICAL, TaskStatus.SCHEDULED),
            ("after", DAY + timedelta(days=1), TaskType.CREATIVE, TaskStatus.SKIPPED),
        ]
    ):
        tasks[name] = await make_task(
            session,
            owner,
            id=UUID(int=5 - index),
            title=name,
            planned_date=day,
            type=task_type,
            status=status,
            completed_at=NOW if status is TaskStatus.DONE else None,
            created_at=NOW if name == "first" else NOW + timedelta(seconds=1),
        )
    tasks["deleted"] = await make_task(session, owner, planned_date=DAY, deleted_at=NOW)
    tasks["foreign"] = await make_task(session, other, planned_date=DAY)
    return owner.id, tasks


@pytest.fixture
async def committed_task(engine: AsyncEngine) -> AsyncIterator[tuple[UUID, UUID]]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await make_user(session, f"{uuid4()}@example.ru")
        task = await make_task(session, user)
        user_id, task_id = user.id, task.id
        await session.commit()
    try:
        yield user_id, task_id
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))


async def test_get_is_scoped_to_owner_and_visible_tasks(
    session: AsyncSession, catalog: tuple[UUID, dict[str, Task]]
) -> None:
    owner_id, tasks = catalog
    repository = TaskRepository(session)
    assert await repository.get(owner_id, tasks["first"].id) is tasks["first"]
    for task_id in (tasks["foreign"].id, tasks["deleted"].id, uuid4()):
        assert await repository.get(owner_id, task_id) is None
        assert await repository.get(owner_id, task_id, for_update=True) is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (TaskListQuery(), ["before", "first", "third", "second", "after"]),
        (TaskListQuery(date=DAY), ["first", "third", "second"]),
        (TaskListQuery.model_validate({"from": DAY}), ["first", "third", "second", "after"]),
        (TaskListQuery.model_validate({"to": DAY}), ["before", "first", "third", "second"]),
        (TaskListQuery.model_validate({"from": DAY, "to": DAY}), ["first", "third", "second"]),
        (TaskListQuery(status=TaskStatus.DONE), ["second"]),
        (TaskListQuery(type=TaskType.PHYSICAL), ["third", "second"]),
        (
            TaskListQuery(date=DAY, status=TaskStatus.SCHEDULED, type=TaskType.PHYSICAL),
            ["third"],
        ),
        (TaskListQuery(date=DAY, type=TaskType.CREATIVE), []),
    ],
)
async def test_list_filters_count_and_order(
    session: AsyncSession,
    catalog: tuple[UUID, dict[str, Task]],
    query: TaskListQuery,
    expected: list[str],
) -> None:
    owner_id, tasks = catalog
    items, total = await TaskRepository(session).list(owner_id, query)
    assert [item.id for item in items] == [tasks[name].id for name in expected]
    assert total == len(expected)


async def test_pagination_preserves_filtered_total_and_stable_order(
    session: AsyncSession, catalog: tuple[UUID, dict[str, Task]]
) -> None:
    owner_id, tasks = catalog
    repository = TaskRepository(session)
    for offset, name in enumerate(["first", "third", "second"]):
        items, total = await repository.list(
            owner_id, TaskListQuery(date=DAY, limit=1, offset=offset)
        )
        assert [item.id for item in items] == [tasks[name].id]
        assert total == 3
    items, total = await repository.list(owner_id, TaskListQuery(date=DAY, limit=1, offset=10))
    assert items == [] and total == 3


async def test_user_without_tasks_gets_empty_list(
    session: AsyncSession, catalog: tuple[UUID, dict[str, Task]]
) -> None:
    items, total = await TaskRepository(session).list(uuid4(), TaskListQuery())
    assert items == [] and total == 0


async def test_save_creates_and_updates_without_managing_status_or_version(
    session: AsyncSession,
) -> None:
    owner = await make_user(session)
    body = TaskCreate(title="Отчёт", type=TaskType.INTELLECTUAL, duration_min=60, planned_date=DAY)
    task = Task(user_id=owner.id, **body.model_dump())
    repository = TaskRepository(session)
    await repository.save(task)
    assert task.id is not None and task.created_at is not None
    assert task.status is TaskStatus.PENDING and task.version == 1
    assert task.priority is TaskPriority.MEDIUM
    task.title = "Новый отчёт"
    task.deadline = NOW
    await repository.save(task)
    stored = await repository.get(owner.id, task.id)
    assert stored is not None and stored.title == "Новый отчёт" and stored.deadline == NOW
    assert stored.version == 1 and stored.status is TaskStatus.PENDING


async def test_save_does_not_commit_the_callers_transaction(session: AsyncSession) -> None:
    owner = await make_user(session)
    repository = TaskRepository(session)
    savepoint = await session.begin_nested()
    task = Task(
        user_id=owner.id,
        title="Черновик",
        type=TaskType.ROUTINE,
        duration_min=5,
        planned_date=DAY,
    )
    await repository.save(task)
    task_id = task.id
    assert await repository.get(owner.id, task_id) is task
    await savepoint.rollback()
    assert await repository.get(owner.id, task_id) is None


async def test_for_update_holds_lock_until_transaction_ends(
    engine: AsyncEngine, committed_task: tuple[UUID, UUID]
) -> None:
    owner_id, task_id = committed_task
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as first, factory() as second:
        async with first.begin():
            assert await TaskRepository(first).get(owner_id, task_id, for_update=True) is not None
            async with second.begin():
                await second.execute(text("SET LOCAL lock_timeout = '200ms'"))
                assert await TaskRepository(second).get(uuid4(), task_id, for_update=True) is None
                with pytest.raises(DBAPIError) as error:
                    await TaskRepository(second).get(owner_id, task_id, for_update=True)
                assert error.value.orig.sqlstate == "55P03"
                await second.rollback()
        async with second.begin():
            assert await TaskRepository(second).get(owner_id, task_id, for_update=True) is not None


async def test_locked_get_refreshes_a_previously_loaded_version(
    engine: AsyncEngine, committed_task: tuple[UUID, UUID]
) -> None:
    owner_id, task_id = committed_task
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as reader, factory() as writer:
        repository = TaskRepository(reader)
        cached = await repository.get(owner_id, task_id)
        assert cached is not None and cached.version == 1
        async with writer.begin():
            updated = await TaskRepository(writer).get(owner_id, task_id, for_update=True)
            assert updated is not None
            updated.title = "Изменено в другой транзакции"
            updated.version = 2
            await TaskRepository(writer).save(updated)
        refreshed = await repository.get(owner_id, task_id, for_update=True)
        assert refreshed is cached and refreshed.version == 2
        assert refreshed.title == "Изменено в другой транзакции"


async def test_soft_deletion_is_hidden_even_if_task_is_cached(
    engine: AsyncEngine, committed_task: tuple[UUID, UUID]
) -> None:
    owner_id, task_id = committed_task
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as reader, factory() as writer:
        repository = TaskRepository(reader)
        assert await repository.get(owner_id, task_id) is not None
        async with writer.begin():
            task = await TaskRepository(writer).get(owner_id, task_id, for_update=True)
            assert task is not None
            task.deleted_at = NOW
            await TaskRepository(writer).save(task)
        assert await repository.get(owner_id, task_id, for_update=True) is None
        items, total = await repository.list(owner_id, TaskListQuery())
        assert items == [] and total == 0
