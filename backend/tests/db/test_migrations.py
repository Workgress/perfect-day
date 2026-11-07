import asyncio
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import delete, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import metadata
from app.modules.users.models import User

pytestmark = pytest.mark.docker

EXPECTED_TABLES = {
    "users",
    "user_profiles",
    "tasks",
    "schedules",
    "schedule_slots",
    "sessions",
    "refresh_tokens",
    "email_tokens",
}


def _diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    return list(compare_metadata(context, metadata))


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def test_downgrade_and_upgrade_again(alembic_config: Config, migrated_url: str) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


async def test_all_tables_created(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = await connection.run_sync(_tables)

    assert tables >= EXPECTED_TABLES


async def test_migrations_match_models(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        diff = await connection.run_sync(_diff)

    assert diff == []


async def test_auth_migration_round_trip_preserves_existing_users(
    engine: AsyncEngine,
    alembic_config: Config,
) -> None:
    user_id = uuid4()
    email = f"migration-{user_id}@example.ru"
    async with engine.begin() as connection:
        await connection.execute(
            User.__table__.insert().values(
                id=user_id,
                email=email,
                password_hash="existing-password-hash",
                is_email_verified=True,
            )
        )

    try:
        await asyncio.to_thread(command.downgrade, alembic_config, "0004")
        async with engine.connect() as connection:
            tables = await connection.run_sync(_tables)
        assert not {"sessions", "refresh_tokens", "email_tokens"} & tables

        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    select(User.email, User.password_hash, User.is_email_verified).where(
                        User.id == user_id
                    )
                )
            ).one()

        assert tuple(row) == (email, "existing-password-hash", True)
    finally:
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
