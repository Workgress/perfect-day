import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import delete, inspect, select, text
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
    "onboarding_completions",
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


@pytest.mark.parametrize("starting_schema", ["0005", "planner_0006", "tasks_0006", "both_0006"])
@pytest.mark.parametrize("zone", ["UTC", "Asia/Yekaterinburg", "Europe/Berlin"])
async def test_upgrade_from_either_historical_0006_preserves_existing_data(
    engine: AsyncEngine, alembic_config: Config, starting_schema: str, zone: str
) -> None:
    """Only the disposable test DB is downgraded/stamped to recreate historical releases."""
    user_id, task_id, null_id, schedule_id, slot_id, receipt_key = (uuid4() for _ in range(6))
    old_date = date(2026, 10, 25)
    precise_deadline = datetime(2026, 10, 25, 14, 35, 42, 123456, UTC)
    expected_deadline = datetime.combine(
        old_date + timedelta(days=1), time.min, ZoneInfo(zone)
    ).astimezone(UTC) - timedelta(microseconds=1)
    has_planner = starting_schema in {"planner_0006", "both_0006"}
    try:
        await asyncio.to_thread(command.downgrade, alembic_config, "0005")
        if has_planner:
            await asyncio.to_thread(command.upgrade, alembic_config, "0006")
        async with engine.begin() as connection:
            await connection.execute(
                User.__table__.insert().values(
                    id=user_id,
                    email=f"upgrade-{user_id}@example.ru",
                    password_hash="keep-hash",
                    is_email_verified=True,
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO user_profiles (user_id, timezone, display_name) "
                    "VALUES (:user_id, :zone, 'Сохранённый профиль')"
                ),
                {"user_id": user_id, "zone": zone},
            )
            for selected_id, deadline in ((task_id, old_date), (null_id, None)):
                await connection.execute(
                    text(
                        "INSERT INTO tasks (id, user_id, title, type, duration_min, "
                        "planned_date, deadline, version) VALUES (:id, :user_id, "
                        "'Сохранённая задача', 'routine', 17, :day, :deadline, 3)"
                    ),
                    {"id": selected_id, "user_id": user_id, "day": old_date, "deadline": deadline},
                )
            await connection.execute(
                text(
                    "INSERT INTO schedules (id, user_id, date, algorithm_version, "
                    "trigger, load_factor, summary) VALUES (:id, :user_id, :day, "
                    "'keep-version', 'initial', 0.65, jsonb_build_object('keep', true))"
                ),
                {"id": schedule_id, "user_id": user_id, "day": old_date},
            )
            await connection.execute(
                text(
                    "INSERT INTO schedule_slots (id, schedule_id, task_id, kind, "
                    "start_at, end_at, explanation) "
                    "VALUES (:id, :schedule_id, :task_id, 'task', "
                    "TIMESTAMPTZ '2026-10-25 08:00:00Z', "
                    "TIMESTAMPTZ '2026-10-25 08:17:00Z', 'Сохранённый слот')"
                ),
                {"id": slot_id, "schedule_id": schedule_id, "task_id": task_id},
            )
            if has_planner:
                await connection.execute(
                    text(
                        "INSERT INTO onboarding_completions "
                        "(user_id, key, request_body, response_body) VALUES (:user_id, :key, "
                        "jsonb_build_object('request', 'keep'), "
                        "jsonb_build_object('response', 'keep'))"
                    ),
                    {"user_id": user_id, "key": receipt_key},
                )
            if starting_schema in {"tasks_0006", "both_0006"}:
                # Historical task 0006 changed the column and allowed exact in-day deadlines.
                await connection.execute(
                    text(
                        "ALTER TABLE tasks ALTER COLUMN deadline TYPE timestamptz "
                        "USING deadline::timestamp AT TIME ZONE 'UTC'"
                    )
                )
                await connection.execute(
                    text("UPDATE tasks SET deadline=:value WHERE id=:id"),
                    {"value": precise_deadline, "id": task_id},
                )
                await connection.execute(text("UPDATE alembic_version SET version_num='0006'"))
                expected_deadline = precise_deadline
            before_user = (
                await connection.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id})
            ).one()
            before_profile = (
                await connection.execute(
                    text("SELECT * FROM user_profiles WHERE user_id=:id"), {"id": user_id}
                )
            ).one()
            before_tasks = list(
                await connection.execute(
                    text(
                        "SELECT id, title, status, version, created_at, updated_at "
                        "FROM tasks WHERE user_id=:id ORDER BY id"
                    ),
                    {"id": user_id},
                )
            )
            before_slot = (
                await connection.execute(
                    text("SELECT * FROM schedule_slots WHERE id=:id"), {"id": slot_id}
                )
            ).one()

        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        # A second upgrade must not shift an existing intraday timestamp to end-of-day.
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
            )
            assert await connection.run_sync(_diff) == []
            assert (
                await connection.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id})
            ).one() == before_user
            assert (
                await connection.execute(
                    text("SELECT * FROM user_profiles WHERE user_id=:id"), {"id": user_id}
                )
            ).one() == before_profile
            assert (
                list(
                    await connection.execute(
                        text(
                            "SELECT id, title, status, version, created_at, updated_at "
                            "FROM tasks WHERE user_id=:id ORDER BY id"
                        ),
                        {"id": user_id},
                    )
                )
                == before_tasks
            )
            assert (
                await connection.execute(
                    text("SELECT * FROM schedule_slots WHERE id=:id"), {"id": slot_id}
                )
            ).one() == before_slot
            assert (
                await connection.scalar(
                    text("SELECT deadline FROM tasks WHERE id=:id"), {"id": task_id}
                )
                == expected_deadline
            )
            assert (
                await connection.scalar(
                    text("SELECT deadline FROM tasks WHERE id=:id"), {"id": null_id}
                )
                is None
            )
            row = (
                await connection.execute(
                    text(
                        "SELECT load_factor, summary, algorithm_version FROM schedules WHERE id=:id"
                    ),
                    {"id": schedule_id},
                )
            ).one()
            assert tuple(row) == (Decimal("0.650"), {"keep": True}, "keep-version")
            if has_planner:
                receipt = (
                    await connection.execute(
                        text(
                            "SELECT request_body, response_body FROM onboarding_completions "
                            "WHERE user_id=:id AND key=:key"
                        ),
                        {"id": user_id, "key": receipt_key},
                    )
                ).one()
                assert tuple(receipt) == ({"request": "keep"}, {"response": "keep"})
    finally:
        await asyncio.to_thread(command.upgrade, alembic_config, "head")
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.id == user_id))
