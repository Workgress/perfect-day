import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import get_current_user
from app.db.session import get_session
from app.main import create_app
from app.modules.schedule.dependencies import get_schedule_reader
from app.modules.schedule.read_models import ScheduleReadResult
from app.modules.schedule.reader import ScheduleReader
from app.modules.users.models import User, UserProfile

EXAMPLES = json.loads(
    (
        Path(__file__).resolve().parents[3] / "contracts/fixtures/schedule_read_examples.json"
    ).read_text(encoding="utf-8")
)


@dataclass
class ReadAPI:
    app: FastAPI
    client: AsyncClient
    user: User
    session: AsyncMock
    reader: MagicMock


@pytest.fixture
async def read_api() -> AsyncIterator[ReadAPI]:
    app = create_app()
    user = User(id=uuid4())
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = UserProfile(
        user_id=user.id, onboarding_completed_at=datetime(2026, 11, 18, tzinfo=UTC)
    )
    reader = MagicMock(spec=ScheduleReader)
    reader.session = session
    reader.get = AsyncMock()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_schedule_reader] = lambda: reader
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield ReadAPI(app, client, user, session, reader)


@pytest.mark.parametrize("example", ["day_with_tasks", "empty_day"])
async def test_get_returns_saved_result_for_authenticated_owner(
    read_api: ReadAPI, example: str
) -> None:
    body = EXAMPLES[example]
    read_api.reader.get.return_value = ScheduleReadResult.model_validate(body)
    response = await read_api.client.get("/api/v1/schedule", params={"date": body["planned_date"]})

    assert response.status_code == 200
    assert response.json() == body
    assert response.headers["cache-control"] == "no-store"
    read_api.reader.get.assert_awaited_once_with(
        read_api.user.id, date.fromisoformat(body["planned_date"])
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "date=",
        "date=2026-2-01",
        "date=2026-02-30",
        "date=2026-11-18T00:00:00Z",
        "date=2026-11-18&date=2026-11-18",
        "date=2026-11-18&date=2026-11-19",
        "date=2026-11-18&user_id=00000000-0000-4000-8000-000000000001",
        "date=2026-11-18&from=2026-11-01",
        "date=2026-11-18&to=2026-11-30",
        "date=2026-11-18&timezone=UTC",
    ],
)
async def test_invalid_query_is_rejected_before_reading(read_api: ReadAPI, query: str) -> None:
    response = await read_api.client.get(f"/api/v1/schedule?{query}")

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert all(field["field"].startswith("query") for field in error["details"]["fields"])
    read_api.reader.get.assert_not_awaited()
    read_api.session.scalar.assert_not_awaited()


@pytest.mark.parametrize("day", ["2000-01-01", "2099-12-31"])
async def test_past_and_future_dates_are_accepted(read_api: ReadAPI, day: str) -> None:
    read_api.reader.get.return_value = None
    response = await read_api.client.get("/api/v1/schedule", params={"date": day})
    assert response.status_code == 404
    read_api.reader.get.assert_awaited_once_with(read_api.user.id, date.fromisoformat(day))


async def test_missing_schedule_is_not_an_empty_success(read_api: ReadAPI) -> None:
    read_api.reader.get.return_value = None
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 404
    assert response.json() == EXAMPLES["missing_schedule"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("missing_profile", [False, True])
async def test_onboarding_is_checked_before_schedule_lookup(
    read_api: ReadAPI, missing_profile: bool
) -> None:
    read_api.session.scalar.return_value = (
        None if missing_profile else UserProfile(user_id=read_api.user.id)
    )
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 409
    assert response.json() == EXAMPLES["onboarding_required"]
    assert response.headers["cache-control"] == "no-store"
    read_api.reader.get.assert_not_awaited()


async def test_incomplete_schedule_error_is_preserved(read_api: ReadAPI) -> None:
    error = EXAMPLES["incomplete_schedule"]["error"]
    read_api.reader.get.side_effect = AppError(409, error["code"], error["message"])
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 409
    assert response.json() == EXAMPLES["incomplete_schedule"]
    assert response.headers["cache-control"] == "no-store"


async def test_database_failure_is_not_reported_as_missing_schedule(read_api: ReadAPI) -> None:
    read_api.reader.get.side_effect = RuntimeError("private database details")
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_missing_token_uses_existing_authentication(read_api: ReadAPI) -> None:
    del read_api.app.dependency_overrides[get_current_user]
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    read_api.reader.get.assert_not_awaited()


async def test_shared_access_error_does_not_read_schedule(read_api: ReadAPI) -> None:
    def unverified() -> User:
        raise AppError(403, "EMAIL_NOT_VERIFIED", "Подтвердите email")

    read_api.app.dependency_overrides[get_current_user] = unverified
    response = await read_api.client.get("/api/v1/schedule?date=2026-11-18")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    assert response.headers["cache-control"] == "no-store"
    read_api.reader.get.assert_not_awaited()
