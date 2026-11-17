from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.tasks.dependencies import get_task_changed_handler
from tests.integration.test_tasks_api import BODY, TasksAPI
from tests.integration.test_tasks_api import alembic_config as alembic_config
from tests.integration.test_tasks_api import auth_api as auth_api
from tests.integration.test_tasks_api import engine as engine
from tests.integration.test_tasks_api import migrated_url as migrated_url
from tests.integration.test_tasks_api import tasks_api as tasks_api

pytestmark = pytest.mark.docker


async def test_default_http_handler_saves_schedule_and_returns_usable_version(
    tasks_api: TasksAPI,
) -> None:
    api = tasks_api.auth
    api.app.dependency_overrides.pop(get_task_changed_handler)
    headers = {"Authorization": f"Bearer {tasks_api.token}"}
    profile = await api.client.patch(
        "/api/v1/me/profile",
        json={"birth_date": "2000-01-01", "birth_time": "12:00:00", "chronotype": "dove"},
        headers=headers,
    )
    assert profile.status_code == 200, profile.text
    completed = await api.client.post(
        "/api/v1/onboarding/complete",
        json={
            "planned_date": BODY["planned_date"],
            "tasks": [{"title": "First task", "type": "routine", "duration_min": 15}],
        },
        headers=headers | {"Idempotency-Key": str(uuid4())},
    )
    assert completed.status_code == 200, completed.text
    response = await tasks_api.request(
        "POST",
        body=BODY
        | {
            "planned_date": "2026-11-13",
            "type": "routine",
            "duration_min": 15,
            "deadline": "2026-11-13T18:00:00+05:00",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["status"] == "scheduled"
    assert (await tasks_api.request("GET", f"/{created['id']}")).json() == created
    changed = await tasks_api.request(
        "PATCH", f"/{created['id']}", {"version": created["version"], "duration_min": 20}
    )
    assert changed.status_code == 200, changed.text
    assert (await tasks_api.request("GET", f"/{created['id']}")).json() == changed.json()
    async with AsyncSession(api.engine) as session:
        plan = await session.scalar(
            select(Schedule).where(
                Schedule.user_id == tasks_api.user_id,
                Schedule.date == date.fromisoformat(changed.json()["planned_date"]),
                Schedule.is_active.is_(True),
            )
        )
        assert plan is not None and plan.version == 2
        assert plan.trigger == ScheduleTrigger.TASK_UPDATED
