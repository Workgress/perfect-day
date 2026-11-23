import asyncio
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.schedule.adapters import task_snapshot
from app.modules.users.models import User
from tests.db.factories import make_task, make_user

pytestmark = pytest.mark.docker


async def test_date_lock_round_trip_and_snapshot_do_not_pin_time(session: AsyncSession) -> None:
    user = await make_user(session)
    ordinary = await make_task(session, user)
    locked = await make_task(session, user, is_date_locked=True)
    await session.refresh(ordinary)
    await session.refresh(locked)
    assert ordinary.is_date_locked is False
    assert locked.is_date_locked is True
    snapshot = task_snapshot(locked)
    assert snapshot.is_date_locked is True
    assert snapshot.is_pinned is False and snapshot.pinned_start is None


async def test_date_lock_migration_preserves_existing_tasks(
    engine: AsyncEngine, alembic_config: Config
) -> None:
    user_id, task_id = uuid4(), uuid4()
    try:
        await asyncio.to_thread(command.downgrade, alembic_config, "0008")
        async with engine.begin() as connection:
            await connection.execute(
                User.__table__.insert().values(
                    id=user_id, email=f"date-lock-{user_id}@example.ru", password_hash="hash"
                )
            )
            before = (
                await connection.execute(
                    text(
                        "INSERT INTO tasks (id, user_id, title, type, duration_min, planned_date, "
                        "version, actual_start) VALUES (:id, :user_id, 'Отчёт', 'routine', 30, "
                        "DATE '2026-11-24', 4, TIMESTAMPTZ '2026-11-24 08:00:00Z') "
                        "RETURNING id, title, planned_date, version, actual_start, "
                        "created_at, updated_at"
                    ),
                    {"id": task_id, "user_id": user_id},
                )
            ).one()

        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            after = (
                await connection.execute(
                    text(
                        "SELECT id, title, planned_date, version, actual_start, created_at, "
                        "updated_at, is_date_locked FROM tasks WHERE id=:id"
                    ),
                    {"id": task_id},
                )
            ).one()
            assert tuple(after[:-1]) == tuple(before) and after.is_date_locked is False
            await connection.execute(
                text("UPDATE tasks SET is_date_locked=true WHERE id=:id"), {"id": task_id}
            )

        await asyncio.to_thread(command.downgrade, alembic_config, "0008")
        async with engine.connect() as connection:
            restored = (
                await connection.execute(
                    text(
                        "SELECT id, title, planned_date, version, actual_start, created_at, "
                        "updated_at FROM tasks WHERE id=:id"
                    ),
                    {"id": task_id},
                )
            ).one()
            assert tuple(restored) == tuple(before)

        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT is_date_locked FROM tasks WHERE id=:id"), {"id": task_id}
                )
                is False
            )
    finally:
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
