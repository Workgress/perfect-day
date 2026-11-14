from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.schedule.models import OnboardingCompletion, Schedule
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task
from app.modules.users.dependencies import get_clock
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url
from tests.integration.test_profile_biorhythm_api import NOW, ProfileAPI
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

pytestmark = pytest.mark.docker


def body(*durations: int) -> dict:
    return {
        "planned_date": NOW.date().isoformat(),
        "tasks": [
            {"title": f"  Задача {i}  ", "type": "routine", "duration_min": duration}
            for i, duration in enumerate(durations or (17, 19))
        ],
    }


async def prepare(api: ProfileAPI) -> None:
    result = await api.patch(
        {"birth_date": "2026-11-06", "birth_time": "12:00:00", "chronotype": "dove"}
    )
    assert result.status_code == 200


async def post(api: ProfileAPI, path: str, data: dict, key: str | None = None):
    headers = {"Authorization": f"Bearer {api.token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return await api.api.client.post(f"/api/v1/onboarding/{path}", json=data, headers=headers)


async def counts(api: ProfileAPI) -> list[int]:
    async with api.api.engine.connect() as connection:
        return [
            int(
                await connection.scalar(
                    select(func.count()).select_from(model).where(model.user_id == api.user_id)
                )
                or 0
            )
            for model in (Task, Schedule, OnboardingCompletion)
        ]


async def test_preview_contract_no_store_and_no_persistence(profile_api: ProfileAPI) -> None:
    await prepare(profile_api)
    response = await post(profile_api, "preview", body())
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"planned_date", "timezone", "slots", "unscheduled_task_indexes"}
    assert data["planned_date"] == NOW.date().isoformat() and data["timezone"] == "UTC"
    assert sorted(item["task_index"] for item in data["slots"]) == [0, 1]
    for slot in data["slots"]:
        assert set(slot) == {"task_index", "start_time", "end_time", "explanation"}
        assert slot["start_time"].endswith(":00") and slot["end_time"].endswith(":00")
        assert slot["explanation"]
    assert await counts(profile_api) == [0, 0, 0]
    assert (await profile_api.get("/me")).json()["onboarding"]["completed_at"] is None


async def test_completion_and_retry_follow_contract_even_after_midnight(
    profile_api: ProfileAPI,
) -> None:
    await prepare(profile_api)
    key, data = str(uuid4()), body()
    response = await post(profile_api, "complete", data, key)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["onboarding"]["completed_at"] is not None
    assert response.json()["onboarding"]["next_step"] is None
    profile_api.api.app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW.replace(day=9))
    retry = await post(profile_api, "complete", data, key)
    assert retry.status_code == 200 and retry.json() == response.json()
    assert await counts(profile_api) == [2, 1, 1]
    changed = body()
    changed["tasks"][0]["title"] = "Задача 0"
    assert (await post(profile_api, "complete", changed, key)).json()["error"][
        "code"
    ] == "IDEMPOTENCY_CONFLICT"
    assert (await post(profile_api, "complete", data, str(uuid4()))).json()["error"][
        "code"
    ] == "ONBOARDING_ALREADY_COMPLETED"


async def test_partial_preview_does_not_confirm_completion(profile_api: ProfileAPI) -> None:
    await prepare(profile_api)
    preview = await post(profile_api, "preview", body(480))
    assert preview.status_code == 200 and preview.json()["unscheduled_task_indexes"] == [0]
    completion = await post(profile_api, "complete", body(480), str(uuid4()))
    assert (
        completion.status_code == 409
        and completion.json()["error"]["code"] == "PLAN_CAPACITY_EXCEEDED"
    )
    assert await counts(profile_api) == [0, 0, 0]


@pytest.mark.parametrize("path", ["preview", "complete"])
async def test_onboarding_requires_bearer_and_verified_email(
    profile_api: ProfileAPI, path: str
) -> None:
    missing = await profile_api.api.client.post(
        f"/api/v1/onboarding/{path}", json=body(), headers={"Idempotency-Key": str(uuid4())}
    )
    assert missing.status_code == 401 and missing.headers["cache-control"] == "no-store"
    assert missing.headers["www-authenticate"] == "Bearer"
    async with profile_api.api.engine.begin() as connection:
        from app.modules.users.models import User

        await connection.execute(
            User.__table__.update()
            .where(User.id == profile_api.user_id)
            .values(is_email_verified=False)
        )
    unverified = await post(profile_api, path, body(), str(uuid4()))
    assert (
        unverified.status_code == 403 and unverified.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    )


@pytest.mark.parametrize("path", ["preview", "complete"])
async def test_incomplete_profile_and_stale_date_use_shared_errors(
    profile_api: ProfileAPI, path: str
) -> None:
    key = str(uuid4())
    incomplete = await post(profile_api, path, body(), key)
    assert (
        incomplete.status_code == 409 and incomplete.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    )
    await prepare(profile_api)
    stale = body()
    stale["planned_date"] = "2026-11-07"
    response = await post(profile_api, path, stale, key)
    assert response.status_code == 409 and response.json()["error"]["details"] == {
        "planned_date": NOW.date().isoformat(),
        "timezone": "UTC",
    }


@pytest.mark.parametrize("path", ["preview", "complete"])
async def test_work_window_limit_is_422_in_both_routes(profile_api: ProfileAPI, path: str) -> None:
    await prepare(profile_api)
    response = await post(profile_api, path, body(480, 121), str(uuid4()))
    assert (
        response.status_code == 422
        and response.json()["error"]["details"]["fields"][0]["field"] == "body.tasks"
    )
    assert await counts(profile_api) == [0, 0, 0]


@pytest.mark.parametrize("key", [None, "bad-uuid"])
async def test_completion_requires_a_valid_idempotency_uuid(
    profile_api: ProfileAPI, key: str | None
) -> None:
    await prepare(profile_api)
    result = await post(profile_api, "complete", body(), key)
    assert result.status_code == 422 and result.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_profile_change_replans_in_the_same_transaction_and_notification_stays_post_commit(
    profile_api: ProfileAPI,
) -> None:
    await prepare(profile_api)
    assert (await post(profile_api, "complete", body(), str(uuid4()))).status_code == 200
    response = await profile_api.patch({"work_end": "19:00:00"})
    assert response.status_code == 200 and await counts(profile_api) == [2, 2, 1]
    assert "work_end" in profile_api.events[-1].changed_fields


async def test_failed_profile_replanning_rolls_back_profile_and_keeps_active_plan(
    profile_api: ProfileAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    await prepare(profile_api)
    assert (await post(profile_api, "complete", body(), str(uuid4()))).status_code == 200
    original = (await profile_api.get("/me")).json()
    events = len(profile_api.events)

    original_handler = ScheduleService.profile_changed

    async def broken(self: ScheduleService, *args: object) -> None:
        await original_handler(self, *args)
        raise AppError(503, "PLANNER_UNAVAILABLE", "Временно недоступен")

    monkeypatch.setattr(ScheduleService, "profile_changed", broken)
    response = await profile_api.patch({"work_end": "19:00:00"})
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert (await profile_api.get("/me")).json() == original
    assert len(profile_api.events) == events and await counts(profile_api) == [2, 1, 1]


async def test_no_schedule_or_task_crud_routes_are_accidentally_added(
    profile_api: ProfileAPI,
) -> None:
    for path in ("/schedule", "/tasks"):
        assert (await profile_api.get(path)).status_code == 404


async def test_same_profile_patch_does_not_create_a_redundant_schedule(
    profile_api: ProfileAPI,
) -> None:
    await prepare(profile_api)
    assert (await post(profile_api, "complete", body(), str(uuid4()))).status_code == 200
    events = len(profile_api.events)
    assert (await profile_api.patch({})).status_code == 200
    assert len(profile_api.events) == events and await counts(profile_api) == [2, 1, 1]


async def test_calendar_date_is_validated_in_the_saved_timezone(profile_api: ProfileAPI) -> None:
    await prepare(profile_api)
    profile_api.api.app.dependency_overrides[get_clock] = lambda: FrozenClock(
        NOW.replace(hour=23, minute=30)
    )
    assert (await profile_api.patch({"timezone": "Pacific/Kiritimati"})).status_code == 200
    stale = await post(profile_api, "preview", body())
    assert (
        stale.status_code == 409
        and stale.json()["error"]["details"]["planned_date"] == "2026-11-09"
    )
    today = body()
    today["planned_date"] = "2026-11-09"
    assert (await post(profile_api, "preview", today)).status_code == 200


async def test_planner_technical_failure_is_retryable_503_over_http(
    profile_api: ProfileAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    await prepare(profile_api)
    original = ScheduleService._calculate

    def unavailable(*args: object) -> None:
        raise RuntimeError("simulated compute failure")

    def calculate(self: ScheduleService, context):
        self.builder = unavailable
        return original(self, context)

    key = str(uuid4())
    with monkeypatch.context() as patch:
        patch.setattr(ScheduleService, "_calculate", calculate)
        result = await post(profile_api, "complete", body(), key)
    assert result.status_code == 503 and result.json()["error"]["code"] == "PLANNER_UNAVAILABLE"
    assert result.headers["cache-control"] == "no-store" and await counts(profile_api) == [0, 0, 0]
    assert (await post(profile_api, "complete", body(), key)).status_code == 200
