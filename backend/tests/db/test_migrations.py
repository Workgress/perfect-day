import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import metadata

pytestmark = pytest.mark.db

EXPECTED_TABLES = {"users", "user_profiles", "tasks", "schedules", "schedule_slots"}


def _diff(connection: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(connection), metadata))


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
