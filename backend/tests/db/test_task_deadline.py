import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.tasks.models import Task
from app.modules.users.models import User, UserProfile
from tests.db.factories import make_task, make_user

pytestmark = pytest.mark.docker


@pytest.mark.parametrize(
    ("profile_timezone", "old_deadline", "expected"),
    [
        ("UTC", date(2026, 11, 11), datetime(2026, 11, 11, 23, 59, 59, 999999, UTC)),
        (
            "Asia/Yekaterinburg",
            date(2026, 11, 11),
            datetime(2026, 11, 11, 18, 59, 59, 999999, UTC),
        ),
        (
            "America/New_York",
            date(2026, 11, 11),
            datetime(2026, 11, 12, 4, 59, 59, 999999, UTC),
        ),
        ("Europe/Berlin", date(2026, 3, 29), datetime(2026, 3, 29, 21, 59, 59, 999999, UTC)),
        ("Europe/Berlin", date(2026, 10, 25), datetime(2026, 10, 25, 22, 59, 59, 999999, UTC)),
        (
            "America/Sao_Paulo",
            date(2018, 11, 3),
            datetime(2018, 11, 4, 2, 59, 59, 999999, UTC),
        ),
        (None, date(2026, 11, 11), datetime(2026, 11, 11, 23, 59, 59, 999999, UTC)),
        ("Asia/Yekaterinburg", None, None),
        (None, None, None),
    ],
)
async def test_deadline_migration_preserves_tasks(
    engine: AsyncEngine,
    alembic_config: Config,
    profile_timezone: str | None,
    old_deadline: date | None,
    expected: datetime | None,
) -> None:
    user_id, task_id = uuid4(), uuid4()
    try:
        await asyncio.to_thread(command.downgrade, alembic_config, "0005")
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
            await connection.execute(
                User.__table__.insert().values(
                    id=user_id, email=f"deadline-{user_id}@example.ru", password_hash="hash"
                )
            )
            if profile_timezone is not None:
                await connection.execute(
                    UserProfile.__table__.insert().values(
                        user_id=user_id, timezone=profile_timezone
                    )
                )
            before = (
                await connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, user_id, title, type, duration_min, planned_date, deadline, "
                        "version, deleted_at) "
                        "VALUES (:id, :user_id, 'Отчёт', 'intellectual', 60, "
                        "DATE '2026-11-11', :deadline, 3, TIMESTAMPTZ '2026-11-12 00:00:00Z') "
                        "RETURNING title, status, version, created_at, updated_at, deleted_at"
                    ),
                    {"id": task_id, "user_id": user_id, "deadline": old_deadline},
                )
            ).one()

        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(
                        Task.deadline,
                        Task.title,
                        Task.status,
                        Task.version,
                        Task.created_at,
                        Task.updated_at,
                        Task.deleted_at,
                    ).where(Task.id == task_id)
                )
            ).one()
        assert row.deadline == expected
        assert tuple(row[1:]) == tuple(before)

        await asyncio.to_thread(command.downgrade, alembic_config, "0005")
        async with engine.connect() as connection:
            restored = await connection.scalar(
                text("SELECT deadline FROM tasks WHERE id = :id"), {"id": task_id}
            )
        assert restored == old_deadline
    finally:
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))


async def test_deadline_timestamp_round_trip(session: AsyncSession) -> None:
    user = await make_user(session)
    deadline = datetime(2026, 11, 12, 14, 35, 42, 123456, timezone(timedelta(hours=5)))
    task = await make_task(session, user, deadline=deadline)
    await session.refresh(task)

    assert task.deadline == datetime(2026, 11, 12, 9, 35, 42, 123456, UTC)
    assert task.deadline.utcoffset() == timedelta(0)
