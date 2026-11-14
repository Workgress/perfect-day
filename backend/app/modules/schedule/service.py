"""Transactional integration for the planner; ordinary task CRUD stays with its owner."""

import logging
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import Clock, parse_timezone, to_utc
from app.modules.planner.constraints import ConstraintError
from app.modules.planner.contracts import (
    FutureDay,
    PlacementChange,
    PlanContext,
    PlanMode,
    PlanResult,
    PlanTask,
    ReplanResult,
    ScheduleBuilder,
    TaskRef,
)
from app.modules.planner.engine import build_schedule
from app.modules.planner.replan import preserve_reservations, replan_remaining_day
from app.modules.planner.time_grid import PlannerTimeError, make_time_grid
from app.modules.schedule.adapters import (
    profile_snapshot,
    quantized_plan,
    quantized_slot,
    saved_slots,
    slot_row,
    stored_summary,
    task_snapshot,
)
from app.modules.schedule.models import OnboardingCompletion, Schedule, ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.schemas import OnboardingRequest, PlanPreview, PreviewSlot
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.events import ProfileChanged
from app.modules.users.models import UserProfile
from app.modules.users.schemas import ProfileDocument
from app.modules.users.service import (
    ProfileService,
    ProfileUserNotFoundError,
    ProfileValidationError,
)

logger = logging.getLogger(__name__)


def _error(code: str, message: str) -> AppError:
    return AppError(409, code, message)


class ScheduleService:
    def __init__(
        self, session: AsyncSession, clock: Clock, *, builder: ScheduleBuilder = build_schedule
    ) -> None:
        self.session = session
        self.clock = clock
        self.repository = ScheduleRepository(session)
        self.profiles = ProfileService(session, clock)
        self.builder = builder

    async def lock_user(self, user_id: UUID) -> None:
        if not await self.repository.lock_user(user_id):
            raise ProfileUserNotFoundError()

    @asynccontextmanager
    async def mutation(self, user_id: UUID) -> AsyncIterator[None]:
        """CRUD integration: lock BEFORE task writes; mutate + replan inside this savepoint.

        The caller owns the outer transaction/commit. Exceptions roll back the task mutation
        and schedules together. Never acquire task locks before this owner lock.

        Within the caller's session.begin():
            async with scheduler.mutation(user_id):
                # Perform the task owner's CRUD operation and flush it here.
                await scheduler.replan(user_id, day, ScheduleTrigger.TASK_UPDATED)
        """
        async with self.session.begin_nested():
            await self.lock_user(user_id)
            yield

    def _calculate(self, context: PlanContext) -> PlanResult:
        try:
            result = self.builder(context)
            represented = [slot.task for slot in result.slots if slot.task is not None]
            represented.extend(item.task for item in result.unscheduled)
            if (
                Counter(represented) != Counter(task.ref for task in context.tasks)
                or result.day != context.day
                or result.timezone != context.profile.timezone
                or result.moves
                or result.future_plans
            ):
                raise ValueError("Planner returned an incomplete or unrelated draft result")
            return result
        except PlannerTimeError as exc:
            raise ProfileValidationError(
                "planned_date", exc.code, "Рабочее время недоступно в выбранную дату"
            ) from exc
        except ConstraintError as exc:
            raise _error("CONFLICT", "Изменение нарушает сохранённые интервалы расписания") from exc
        except Exception as exc:
            logger.exception("Planner calculation failed")
            raise AppError(503, "PLANNER_UNAVAILABLE", "Планировщик временно недоступен") from exc

    async def _draft_context(
        self, user_id: UUID, body: OnboardingRequest, mode: PlanMode
    ) -> PlanContext:
        profile = profile_snapshot(await self.profiles.get_profile(user_id))
        now = to_utc(self.clock.now())
        today = now.astimezone(parse_timezone(profile.timezone)).date()
        if body.planned_date != today:
            raise AppError(
                409,
                "PLANNED_DATE_CHANGED",
                "Текущая дата изменилась",
                {
                    "planned_date": today.isoformat(),
                    "timezone": profile.timezone,
                },
            )
        tasks = tuple(
            PlanTask(TaskRef(task_index=index), task.type.value, task.duration_min, today)
            for index, task in enumerate(body.tasks)
        )
        context = PlanContext(profile, today, now, tasks, mode)
        try:
            grid = make_time_grid(context)
        except PlannerTimeError as exc:
            raise ProfileValidationError(
                "planned_date", exc.code, "Проверьте рабочее время выбранной даты"
            ) from exc
        window = (grid.work_window.end - grid.work_window.start) // timedelta(minutes=1)
        if sum(task.duration_min for task in tasks) > window:
            raise ProfileValidationError(
                "tasks", "WORK_WINDOW_EXCEEDED", "Общая длительность превышает рабочее окно"
            )
        return context

    async def preview(self, user_id: UUID, body: OnboardingRequest) -> PlanPreview:
        context = await self._draft_context(user_id, body, "preview")
        plan = self._calculate(context)
        tz = parse_timezone(context.profile.timezone)
        slots = []
        for item in plan.slots:
            if item.task is None:
                continue
            assert item.task.task_index is not None and item.explanation
            slots.append(
                PreviewSlot(
                    task_index=item.task.task_index,
                    start_time=item.interval.start.astimezone(tz).time().replace(tzinfo=None),
                    end_time=item.interval.end.astimezone(tz).time().replace(tzinfo=None),
                    explanation=item.explanation,
                )
            )
        return PlanPreview(
            planned_date=context.day,
            timezone=context.profile.timezone,
            slots=slots,
            unscheduled_task_indexes=sorted(
                item.task.task_index
                for item in plan.unscheduled
                if item.task.task_index is not None
            ),
        )

    async def complete(self, user_id: UUID, key: UUID, body: OnboardingRequest) -> ProfileDocument:
        """Caller owns the outer transaction; even caught errors leave no partial operation."""
        async with self.mutation(user_id):
            original = body.model_dump(mode="json")
            receipt = await self.repository.receipt(user_id, key)
            if receipt is not None:
                if receipt.request_body != original:
                    raise _error("IDEMPOTENCY_CONFLICT", "Ключ уже использован с другим содержимым")
                return ProfileDocument.model_validate(receipt.response_body)
            state = await self.profiles.get_profile(user_id)
            if state is not None and state.onboarding_completed_at is not None:
                raise _error("ONBOARDING_ALREADY_COMPLETED", "Настройка уже завершена")
            context = await self._draft_context(user_id, body, "initial")
            if await self.repository.tasks(
                user_id, (context.day,), set()
            ) or await self.repository.active(user_id, (context.day,)):
                raise _error("CONFLICT", "На эту дату уже есть задачи или расписание")
            plan = self._calculate(context)
            if plan.unscheduled:
                raise _error("PLAN_CAPACITY_EXCEEDED", "Все задачи не помещаются в расписание")
            # Initial index ties must retain the same order after conversion to persisted UUIDs.
            ids = sorted((uuid4() for _ in body.tasks), key=lambda value: value.int)
            refs = {index: TaskRef(task_id=task_id) for index, task_id in enumerate(ids)}
            for index, draft in enumerate(body.tasks):
                self.session.add(
                    Task(
                        id=refs[index].task_id,
                        user_id=user_id,
                        title=draft.title.strip(),
                        type=draft.type,
                        duration_min=draft.duration_min,
                        planned_date=context.day,
                        status=TaskStatus.SCHEDULED,
                        created_at=context.now,
                    )
                )
            await self.session.flush()
            plan = replace(
                plan,
                slots=tuple(
                    replace(item, task=refs[item.task.task_index])
                    if item.task is not None and item.task.task_index is not None
                    else item
                    for item in plan.slots
                ),
                status_changes=(),
            )
            await self._save_plan(user_id, quantized_plan(plan), ScheduleTrigger.INITIAL)
            profile = await self.session.get(UserProfile, user_id)
            assert profile is not None
            profile.onboarding_completed_at = context.now
            await self.session.flush()
            document = await self.profiles.get_document(user_id)
            self.session.add(
                OnboardingCompletion(
                    user_id=user_id,
                    key=key,
                    request_body=original,
                    response_body=document.model_dump(mode="json"),
                )
            )
            await self.session.flush()
            return document

    async def _save_plan(self, user_id: UUID, plan: PlanResult, trigger: ScheduleTrigger) -> None:
        version = await self.repository.next_version(user_id, plan.day)
        old = (await self.repository.active(user_id, (plan.day,))).get(plan.day)
        if old is not None:
            old.is_active = False
            await self.session.flush()
        row = Schedule(
            user_id=user_id,
            date=plan.day,
            version=version,
            is_active=True,
            algorithm_version=plan.algorithm_version,
            critical_level=plan.metrics.critical_level,
            load_factor=Decimal(str(plan.metrics.load_factor)),
            trigger=trigger,
            summary=stored_summary(plan),
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add_all(slot_row(row, item) for item in plan.slots)
        await self.session.flush()

    async def replan(self, user_id: UUID, day: date, trigger: ScheduleTrigger) -> ReplanResult:
        async with self.mutation(user_id):
            state = await self.profiles.get_profile(user_id)
            if state is None or state.onboarding_completed_at is None:
                raise _error("ONBOARDING_REQUIRED", "Завершите настройку профиля")
            profile = profile_snapshot(state)
            now = to_utc(self.clock.now())
            days = tuple(day + timedelta(days=i) for i in range(min(7, (date.max - day).days) + 1))
            active = await self.repository.active(user_id, days)
            history = {
                slot.task_id
                for row in active.values()
                for slot in row.slots
                if slot.task_id is not None
            }
            rows = await self.repository.tasks(user_id, days, history)
            by_id = {row.id: row for row in rows}
            snapshots = {}
            for selected in days:
                previous = saved_slots(active.get(selected), by_id)
                historical = {
                    slot.task.task_id
                    for slot in previous
                    if slot.task is not None
                    and (
                        slot.interval.start <= now
                        or by_id[cast(UUID, slot.task.task_id)].status == TaskStatus.DONE
                    )
                }
                tasks = tuple(
                    task_snapshot(row)
                    for row in rows
                    if (row.planned_date == selected and row.deleted_at is None)
                    or row.id in historical
                )
                if any(task.planned_date != selected for task in tasks):
                    raise _error("CONFLICT", "Дата исторической задачи не совпадает с расписанием")
                snapshots[selected] = (
                    PlanContext(profile, selected, now, tasks, "replan"),
                    previous,
                )
            source, previous = snapshots[day]
            try:
                future = tuple(
                    FutureDay(selected, ctx.tasks, preserve_reservations(ctx, saved))
                    for selected, (ctx, saved) in snapshots.items()
                    if selected != day
                )
                source = replace(source, future_days=future)
                calculated = replan_remaining_day(source, previous)
            except ConstraintError as exc:
                raise _error(
                    "CONFLICT", "Изменение нарушает сохранённые интервалы расписания"
                ) from exc
            except PlannerTimeError as exc:
                raise ProfileValidationError(
                    "planned_date", exc.code, "Проверьте рабочее время"
                ) from exc
            except Exception as exc:
                logger.exception("Planner replanning failed")
                raise AppError(
                    503, "PLANNER_UNAVAILABLE", "Планировщик временно недоступен"
                ) from exc
            plan = quantized_plan(calculated.plan)
            changes = []
            for item in calculated.changes:
                before = quantized_slot(item.before) if item.before is not None else None
                after = quantized_slot(item.after) if item.after is not None else None
                if (
                    before is not None
                    and after is not None
                    and replace(before, preservation=None) == replace(after, preservation=None)
                ):
                    continue
                changes.append(
                    PlacementChange(item.task, item.kind, before, after, item.reason_codes)
                )
            changed_tasks: set[UUID] = set()
            for move in plan.moves:
                assert move.task.task_id is not None
                row = by_id[move.task.task_id]
                row.moved_from_date = move.from_date
                row.planned_date = move.to_date
                changed_tasks.add(row.id)
            for target in (plan, *plan.future_plans):
                for change in target.status_changes:
                    assert change.task.task_id is not None
                    row = by_id[change.task.task_id]
                    if row.deleted_at is None:
                        row.status = TaskStatus(change.next)
                        changed_tasks.add(row.id)
                await self._save_plan(user_id, target, trigger)
            for task_id in changed_tasks:
                by_id[task_id].version += 1
            await self.session.flush()
            return ReplanResult(plan, tuple(changes))

    async def profile_changed(self, event: ProfileChanged) -> None:
        state = await self.profiles.get_profile(event.user_id)
        if state is None or state.onboarding_completed_at is None:
            return
        day = to_utc(event.occurred_at).astimezone(parse_timezone(state.timezone)).date()
        # Profile PATCH already owns the parent lock and the outer transaction.
        # Existing future versions must also reflect the new profile, not just today's plan.
        days = {day, *await self.repository.active_dates(event.user_id, day)}
        for selected in sorted(days):
            await self.replan(event.user_id, selected, ScheduleTrigger.PROFILE_CHANGED)
