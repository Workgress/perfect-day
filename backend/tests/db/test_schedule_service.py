import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.time import FrozenClock
from app.modules.planner.contracts import PlanContext, PlanResult
from app.modules.schedule.models import (
    OnboardingCompletion,
    Schedule,
    ScheduleSlot,
    ScheduleTrigger,
)
from app.modules.schedule.schemas import OnboardingRequest
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.models import User, UserProfile
from app.modules.users.schemas import ProfilePatch
from app.modules.users.service import ProfileService
from tests.db.factories import make_task, make_user

pytestmark = pytest.mark.docker
DAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 7, tzinfo=UTC)
CLOCK = FrozenClock(NOW)


def request(
    *durations: int, title: str = "  Первая задача  ", day: date = DAY
) -> OnboardingRequest:
    return OnboardingRequest.model_validate(
        {
            "planned_date": day.isoformat(),
            "tasks": [
                {"title": title, "type": "routine", "duration_min": duration}
                for duration in durations or (17,)
            ],
        }
    )


async def setup_user(session: AsyncSession, *, elapsed: int = 2, completed: bool = False) -> User:
    user = await make_user(session, f"planner-{uuid4()}@example.ru")
    await ProfileService(session, CLOCK).update_profile(
        user.id,
        ProfilePatch.model_validate(
            {
                "birth_date": (DAY - timedelta(days=elapsed)).isoformat(),
                "birth_time": "12:00:00",
                "chronotype": "dove",
            }
        ),
    )
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.work_days = [1, 2, 3, 4, 5, 6, 7]
    if completed:
        profile.onboarding_completed_at = NOW
    await session.flush()
    return user


async def counts(session: AsyncSession, user_id: UUID) -> tuple[int, int, int]:
    return tuple(
        [
            int(
                await session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )
                or 0
            )
            for model in (Task, Schedule, OnboardingCompletion)
        ]
    )  # type: ignore[return-value]


async def test_preview_has_no_writes_and_keeps_original_indexes(session: AsyncSession) -> None:
    user = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    result = await service.preview(user.id, request(17, 19, 23))
    assert sorted(slot.task_index for slot in result.slots) == [0, 1, 2]
    assert all(
        slot.explanation and slot.start_time.second == slot.end_time.second == 0
        for slot in result.slots
    )
    assert not result.unscheduled_task_indexes and await counts(session, user.id) == (0, 0, 0)
    assert await service.preview(user.id, request(17, 19, 23)) == result


async def test_completion_saves_tasks_plan_and_permanent_exact_receipt(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    key, body = uuid4(), request(17, 19)
    result = await service.complete(user.id, key, body)
    assert result.onboarding.completed_at == NOW and result.onboarding.next_step is None
    assert await counts(session, user.id) == (2, 1, 1)
    tasks = list(await session.scalars(select(Task).where(Task.user_id == user.id)))
    assert all(row.title == "Первая задача" and row.status == TaskStatus.SCHEDULED for row in tasks)
    receipt = await session.get(OnboardingCompletion, (user.id, key))
    assert receipt is not None and receipt.request_body["tasks"][0]["title"] == "  Первая задача  "
    plan = await session.scalar(select(Schedule).where(Schedule.user_id == user.id))
    assert plan is not None and plan.version == 1 and plan.is_active
    slots = list(
        await session.scalars(select(ScheduleSlot).where(ScheduleSlot.schedule_id == plan.id))
    )
    assert {row.task_id for row in slots if row.task_id} == {row.id for row in tasks}
    assert plan.summary["metrics"]["planned_min"] == 36


async def test_successful_retry_precedes_new_date_and_current_profile_validation(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    key, body = uuid4(), request()
    original = await ScheduleService(session, CLOCK).complete(user.id, key, body)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch(timezone="Asia/Yekaterinburg")
    )
    later = ScheduleService(session, FrozenClock(NOW + timedelta(days=1)))
    assert await later.complete(user.id, key, body) == original
    assert await counts(session, user.id) == (1, 1, 1)
    with pytest.raises(AppError) as conflict:
        await later.complete(user.id, key, request(title="Первая задача"))
    assert conflict.value.body.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(AppError) as completed:
        await later.complete(user.id, uuid4(), body)
    assert completed.value.body.code == "ONBOARDING_ALREADY_COMPLETED"


async def test_partial_preview_is_allowed_but_completion_rolls_back_and_key_is_reusable(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    key, body = uuid4(), request(480)
    preview = await service.preview(user.id, body)
    assert preview.unscheduled_task_indexes == [0]
    with pytest.raises(AppError) as error:
        await service.complete(user.id, key, body)
    assert error.value.body.code == "PLAN_CAPACITY_EXCEEDED"
    assert await counts(session, user.id) == (0, 0, 0)
    profile = await ProfileService(session, CLOCK).get_profile(user.id)
    assert profile is not None and profile.onboarding_completed_at is None
    profile_row = await session.get(UserProfile, user.id)
    assert profile_row is not None
    profile_row.lunch_duration_min = 0
    await session.flush()
    assert (await service.complete(user.id, key, body)).onboarding.completed_at == NOW


@pytest.mark.parametrize("method", ["preview", "complete"])
async def test_duration_sum_is_checked_against_work_window(
    session: AsyncSession, method: str
) -> None:
    user = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    with pytest.raises(AppError) as error:
        if method == "preview":
            await service.preview(user.id, request(480, 121))
        else:
            await service.complete(user.id, uuid4(), request(480, 121))
    assert (
        error.value.status_code == 422
        and error.value.body.details["fields"][0]["field"] == "body.tasks"
    )
    assert await counts(session, user.id) == (0, 0, 0)


async def test_initial_failure_after_plan_write_rolls_back_all_rows(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    save = service._save_plan

    async def broken(*args: object) -> None:
        await save(*args)  # type: ignore[arg-type]
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(service, "_save_plan", broken)
    with pytest.raises(RuntimeError):
        await service.complete(user.id, uuid4(), request())
    assert await counts(session, user.id) == (0, 0, 0)
    profile = await ProfileService(session, CLOCK).get_profile(user.id)
    assert profile is not None and profile.onboarding_completed_at is None


async def test_technical_planner_failure_is_503_without_side_effects(session: AsyncSession) -> None:
    user = await setup_user(session)

    def unavailable(ctx: PlanContext) -> PlanResult:
        raise RuntimeError("calculation failed")

    service = ScheduleService(session, CLOCK, builder=unavailable)
    with pytest.raises(AppError) as error:
        await service.complete(user.id, uuid4(), request())
    assert error.value.status_code == 503 and error.value.body.code == "PLANNER_UNAVAILABLE"
    assert await counts(session, user.id) == (0, 0, 0)


async def test_profile_date_and_user_guards(session: AsyncSession) -> None:
    service = ScheduleService(session, CLOCK)
    with pytest.raises(AppError) as missing:
        await service.complete(uuid4(), uuid4(), request())
    assert missing.value.status_code == 401
    user = await make_user(session, f"{uuid4()}@example.ru")
    with pytest.raises(AppError) as incomplete:
        await service.complete(user.id, uuid4(), request())
    assert incomplete.value.body.code == "PROFILE_INCOMPLETE"
    user = await setup_user(session)
    with pytest.raises(AppError) as stale:
        await service.complete(user.id, uuid4(), request(day=DAY - timedelta(days=1)))
    assert (
        stale.value.body.code == "PLANNED_DATE_CHANGED"
        and stale.value.body.details["planned_date"] == DAY.isoformat()
    )


async def test_load_factor_preserves_three_decimal_places_in_postgres(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=322)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request(5))
    factor = await session.scalar(select(Schedule.load_factor).where(Schedule.user_id == user.id))
    assert factor == Decimal("0.585")


async def test_replan_versions_keep_history_and_update_statuses(session: AsyncSession) -> None:
    user = await setup_user(session)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    old = await session.scalar(select(Schedule).where(Schedule.user_id == user.id))
    assert old is not None
    old_slots = list(
        await session.scalars(select(ScheduleSlot).where(ScheduleSlot.schedule_id == old.id))
    )
    first = next(row for row in old_slots if row.task_id)
    service = ScheduleService(session, FrozenClock(first.start_at + timedelta(minutes=1)))
    async with service.mutation(user.id):
        added = await make_task(session, user, type="routine", duration_min=15, planned_date=DAY)
        result = await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    assert any(change.task.task_id == added.id for change in result.changes)
    rows = list(
        await session.scalars(
            select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.version)
        )
    )
    assert [(row.version, row.is_active) for row in rows] == [(1, False), (2, True)]
    newest = list(
        await session.scalars(select(ScheduleSlot).where(ScheduleSlot.schedule_id == rows[1].id))
    )
    retained = next(row for row in newest if row.task_id == first.task_id)
    assert (retained.start_at, retained.end_at, retained.explanation) == (
        first.start_at,
        first.end_at,
        first.explanation,
    )
    assert added.status == TaskStatus.SCHEDULED and added.version == 2
    again = await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert not again.changes


async def test_crud_mutation_and_replan_roll_back_together(session: AsyncSession) -> None:
    user = await setup_user(session, completed=True)
    service = ScheduleService(session, CLOCK)
    with pytest.raises(RuntimeError):
        async with service.mutation(user.id):
            await make_task(session, user, planned_date=DAY)
            await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
            raise RuntimeError("abort whole operation")
    assert await counts(session, user.id) == (0, 0, 0)


async def test_protected_task_edit_is_rejected_without_committing_the_edit(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    old = await session.scalar(select(Schedule).where(Schedule.user_id == user.id))
    assert old is not None
    saved = await session.scalar(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_id == old.id, ScheduleSlot.task_id.is_not(None)
        )
    )
    assert saved is not None
    service = ScheduleService(session, FrozenClock(saved.start_at + timedelta(minutes=1)))
    task_id = saved.task_id
    with pytest.raises(AppError) as error:
        async with service.mutation(user.id):
            task = await session.get(Task, task_id)
            assert task is not None
            task.duration_min = 30
            await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert error.value.body.code == "CONFLICT"
    task = await session.get(Task, task_id)
    assert task is not None and task.duration_min == 17
    assert await counts(session, user.id) == (1, 1, 1)


async def test_soft_deleted_history_is_retained_and_future_deleted_work_is_removed(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request(17, 19))
    slots = list(
        await session.scalars(
            select(ScheduleSlot)
            .join(Schedule)
            .where(Schedule.user_id == user.id, ScheduleSlot.task_id.is_not(None))
            .order_by(ScheduleSlot.start_at)
        )
    )
    service = ScheduleService(session, FrozenClock(slots[0].start_at + timedelta(minutes=1)))
    async with service.mutation(user.id):
        for saved in slots:
            row = await session.get(Task, saved.task_id)
            assert row is not None
            row.deleted_at = NOW
        result = await service.replan(user.id, DAY, ScheduleTrigger.TASK_DELETED)
    assert {item.task.task_id for item in result.plan.slots if item.task} == {slots[0].task_id}
    assert result.plan.metrics.planned_min == 0


async def test_critical_moves_and_both_day_versions_are_saved_atomically(
    session: AsyncSession,
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    row = await make_task(session, user, planned_date=DAY, duration_min=60)
    result = await ScheduleService(session, CLOCK).replan(
        user.id, DAY, ScheduleTrigger.TASK_CREATED
    )
    assert len(result.plan.moves) == len(result.plan.future_plans) == 1
    move = result.plan.moves[0]
    assert row.planned_date == move.to_date and row.moved_from_date == DAY
    assert row.status == TaskStatus.SCHEDULED and row.version == 2
    schedules = list(await session.scalars(select(Schedule).where(Schedule.user_id == user.id)))
    assert {item.date for item in schedules} == {DAY, move.to_date}
    target = next(item for item in schedules if item.date == move.to_date)
    assert (
        await session.scalar(
            select(ScheduleSlot.task_id).where(
                ScheduleSlot.schedule_id == target.id, ScheduleSlot.task_id == row.id
            )
        )
        == row.id
    )


async def test_replan_before_onboarding_is_blocked_and_users_are_isolated(
    session: AsyncSession,
) -> None:
    owner = await setup_user(session)
    service = ScheduleService(session, CLOCK)
    with pytest.raises(AppError) as error:
        await service.replan(owner.id, DAY, ScheduleTrigger.TASK_CREATED)
    assert error.value.body.code == "ONBOARDING_REQUIRED"
    other = await setup_user(session, completed=True)
    row = await make_task(session, owner, planned_date=DAY)
    result = await service.replan(other.id, DAY, ScheduleTrigger.TASK_CREATED)
    assert not any(item.task for item in result.plan.slots)
    assert row.status == TaskStatus.PENDING


@pytest.fixture
async def committed_planner_user(engine: AsyncEngine) -> AsyncIterator[UUID]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await setup_user(session)
        user_id = user.id
        await session.commit()
    try:
        yield user_id
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def test_concurrent_completion_with_same_key_creates_one_operation(
    engine: AsyncEngine, committed_planner_user: UUID
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = uuid4()

    async def complete() -> dict:
        async with factory() as session, session.begin():
            return (
                await ScheduleService(session, CLOCK).complete(
                    committed_planner_user, key, request()
                )
            ).model_dump(mode="json")

    first, second = await asyncio.gather(complete(), complete())
    assert first == second
    async with factory() as session:
        assert await counts(session, committed_planner_user) == (1, 1, 1)


async def test_concurrent_replans_have_unique_monotonic_versions(
    engine: AsyncEngine, committed_planner_user: UUID
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await ScheduleService(session, CLOCK).complete(committed_planner_user, uuid4(), request())

    async def replan() -> None:
        async with factory() as session, session.begin():
            await ScheduleService(session, CLOCK).replan(
                committed_planner_user, DAY, ScheduleTrigger.TASK_UPDATED
            )

    await asyncio.gather(replan(), replan())
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(Schedule)
                .where(Schedule.user_id == committed_planner_user)
                .order_by(Schedule.version)
            )
        )
        assert [(row.version, row.is_active) for row in rows] == [(1, False), (2, False), (3, True)]


async def test_receipts_are_scoped_to_the_authenticated_owner(session: AsyncSession) -> None:
    first, second = await setup_user(session), await setup_user(session)
    key = uuid4()
    service = ScheduleService(session, CLOCK)
    a = await service.complete(first.id, key, request())
    b = await service.complete(second.id, key, request())
    assert a.id != b.id and a.id == first.id and b.id == second.id
    assert await counts(session, first.id) == await counts(session, second.id) == (1, 1, 1)


async def test_uuid_conversion_retains_initial_index_tie_order(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await setup_user(session)
    ids = iter((UUID(int=2), UUID(int=1)))
    monkeypatch.setattr("app.modules.schedule.service.uuid4", lambda: next(ids))
    service = ScheduleService(session, CLOCK)
    await service.complete(user.id, UUID(int=99), request(17, 17))
    result = await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert not result.changes


async def test_target_day_storage_failure_rolls_back_source_move_and_status(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await setup_user(session, elapsed=14, completed=True)
    task = await make_task(session, user, planned_date=DAY)
    task_id = task.id
    service = ScheduleService(session, CLOCK)
    save = service._save_plan
    calls = 0

    async def broken(*args: object) -> None:
        nonlocal calls
        calls += 1
        await save(*args)  # type: ignore[arg-type]
        if calls == 2:
            raise RuntimeError("target failure")

    monkeypatch.setattr(service, "_save_plan", broken)
    with pytest.raises(RuntimeError):
        await service.replan(user.id, DAY, ScheduleTrigger.TASK_CREATED)
    stored = await session.get(Task, task_id)
    assert stored is not None and stored.planned_date == DAY and stored.moved_from_date is None
    assert stored.status == TaskStatus.PENDING and stored.version == 1
    assert await counts(session, user.id) == (1, 0, 0)


@pytest.mark.parametrize("different_key", [False, True])
async def test_competing_completion_operations_have_one_winner(
    engine: AsyncEngine, committed_planner_user: UUID, different_key: bool
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = uuid4()

    async def complete(selected_key: UUID, title: str) -> str:
        try:
            async with factory() as session, session.begin():
                await ScheduleService(session, CLOCK).complete(
                    committed_planner_user, selected_key, request(title=title)
                )
            return "success"
        except AppError as exc:
            return exc.body.code

    results = await asyncio.gather(
        complete(key, "Первый"), complete(uuid4() if different_key else key, "Второй")
    )
    assert sorted(results) == sorted(
        ["success", "ONBOARDING_ALREADY_COMPLETED" if different_key else "IDEMPOTENCY_CONFLICT"]
    )
    async with factory() as session:
        assert await counts(session, committed_planner_user) == (1, 1, 1)


async def test_profile_change_refreshes_existing_future_schedule_versions(
    session: AsyncSession,
) -> None:
    from app.modules.users.events import ProfileChanged

    user = await setup_user(session, completed=True)
    future_day = DAY + timedelta(days=1)
    await make_task(session, user, type="routine", duration_min=17, planned_date=future_day)
    service = ScheduleService(session, CLOCK)
    await service.replan(user.id, future_day, ScheduleTrigger.TASK_CREATED)
    await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch.model_validate({"work_end": "19:00:00"})
    )
    await service.profile_changed(ProfileChanged(user.id, frozenset({"work_end"}), NOW))
    rows = list(
        await session.scalars(
            select(Schedule)
            .where(Schedule.user_id == user.id, Schedule.date == future_day)
            .order_by(Schedule.version)
        )
    )
    assert [(row.version, row.is_active) for row in rows] == [(1, False), (2, True)]
    assert rows[1].summary["metrics"]["capacity_min"] == 600


async def test_incomplete_legacy_profile_does_not_produce_a_partial_plan(
    session: AsyncSession,
) -> None:
    from datetime import time

    user = await setup_user(session)
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.lunch_start = time(12, 0, 30)
    await session.flush()
    with pytest.raises(AppError) as error:
        await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    assert error.value.body.code == "PROFILE_INCOMPLETE" and await counts(session, user.id) == (
        0,
        0,
        0,
    )


async def test_existing_tasks_of_an_incomplete_user_are_not_silently_replaced(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    await make_task(session, user, planned_date=DAY)
    with pytest.raises(AppError) as error:
        await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    assert error.value.body.code == "CONFLICT" and await counts(session, user.id) == (1, 0, 0)


async def test_broken_calculator_cannot_claim_success_while_losing_drafts(
    session: AsyncSession,
) -> None:
    from dataclasses import replace

    from app.modules.planner.engine import build_schedule

    user = await setup_user(session)

    def broken(ctx: PlanContext) -> PlanResult:
        return replace(build_schedule(ctx), slots=(), unscheduled=())

    with pytest.raises(AppError) as error:
        await ScheduleService(session, CLOCK, builder=broken).complete(user.id, uuid4(), request())
    assert error.value.body.code == "PLANNER_UNAVAILABLE" and await counts(session, user.id) == (
        0,
        0,
        0,
    )


async def test_date_change_of_protected_history_is_rolled_back(session: AsyncSession) -> None:
    user = await setup_user(session)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    schedule = await session.scalar(select(Schedule).where(Schedule.user_id == user.id))
    assert schedule is not None
    saved = await session.scalar(
        select(ScheduleSlot).where(
            ScheduleSlot.schedule_id == schedule.id, ScheduleSlot.task_id.is_not(None)
        )
    )
    assert saved is not None and saved.task_id is not None
    task_id = saved.task_id
    service = ScheduleService(session, FrozenClock(saved.start_at + timedelta(minutes=1)))
    with pytest.raises(AppError) as error:
        async with service.mutation(user.id):
            task = await session.get(Task, task_id)
            assert task is not None
            task.planned_date = DAY + timedelta(days=1)
            await service.replan(user.id, DAY, ScheduleTrigger.TASK_UPDATED)
    assert error.value.body.code == "CONFLICT"
    restored = await session.get(Task, task_id)
    assert restored is not None and restored.planned_date == DAY


async def test_hard_delete_cannot_destroy_a_referenced_historical_slot(
    session: AsyncSession,
) -> None:
    user = await setup_user(session)
    await ScheduleService(session, CLOCK).complete(user.id, uuid4(), request())
    service = ScheduleService(session, CLOCK)
    task = await session.scalar(select(Task).where(Task.user_id == user.id))
    assert task is not None
    task_id = task.id
    with pytest.raises(AppError) as error:
        async with service.mutation(user.id):
            await session.delete(task)
            await session.flush()
            await service.replan(user.id, DAY, ScheduleTrigger.TASK_DELETED)
    assert error.value.body.code == "CONFLICT"
    assert await session.get(Task, task_id) is not None
    assert await counts(session, user.id) == (1, 1, 1)


async def test_unplaced_scheduled_task_becomes_pending_after_replan(session: AsyncSession) -> None:
    user = await setup_user(session)
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.lunch_duration_min = 0
    await session.flush()
    service = ScheduleService(session, CLOCK)
    await service.complete(user.id, uuid4(), request(480))
    profile.lunch_duration_min = 60
    await session.flush()
    result = await service.replan(user.id, DAY, ScheduleTrigger.PROFILE_CHANGED)
    assert result.plan.unscheduled
    task = await session.scalar(select(Task).where(Task.user_id == user.id))
    assert task is not None and task.status == TaskStatus.PENDING and task.version == 2


@pytest.mark.parametrize("lunch", [False, True])
async def test_dst_work_and_lunch_validation_remain_shared_422_errors(
    session: AsyncSession, lunch: bool
) -> None:
    from datetime import time

    user = await setup_user(session)
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.timezone = "Europe/Berlin"
    profile.work_start = time.min if lunch else time(2, 30)
    profile.work_end = time(5)
    profile.lunch_start = time(2, 30)
    await session.flush()
    clock = FrozenClock(datetime(2026, 3, 29, tzinfo=UTC))
    with pytest.raises(AppError) as error:
        await ScheduleService(session, clock).preview(user.id, request(day=date(2026, 3, 29)))
    assert error.value.status_code == 422 and error.value.body.code == "VALIDATION_ERROR"
