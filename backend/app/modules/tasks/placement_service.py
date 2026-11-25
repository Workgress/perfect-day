from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AppError
from app.core.time import Clock, to_utc
from app.modules.planner.constraints import ConstraintError
from app.modules.planner.contracts import Interval, PlanContext
from app.modules.planner.time_grid import PlannerTimeError, make_time_grid
from app.modules.schedule.adapters import profile_snapshot, saved_slots, task_snapshot
from app.modules.schedule.placement import PlacementRejection, selected_placement_refusals
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.events import TaskChanged, TaskChangedHandler, task_changed
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.placement_schemas import (
    TaskMoveRequest,
    TaskPinRequest,
    TaskPlacementRequest,
)
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskResponse
from app.modules.tasks.service import TaskStatusConflictError
from app.modules.users.service import ProfileValidationError


def _move_error(reason_code: str, message: str) -> AppError:
    return AppError(409, "TASK_MOVE_NOT_ALLOWED", message, {"reason_code": reason_code})


def _placement_error(refusal: PlacementRejection) -> AppError:
    if refusal.code != "INTERVAL_OCCUPIED" or refusal.conflict is None:
        return _move_error(refusal.code, refusal.message)
    conflict = refusal.conflict
    details: dict[str, JsonValue] = {
        "reason_code": refusal.code,
        "start_at": conflict.interval.start.isoformat().replace("+00:00", "Z"),
        "end_at": conflict.interval.end.isoformat().replace("+00:00", "Z"),
        "kind": conflict.kind,
        "conflicting_task_id": str(conflict.task.task_id) if conflict.task is not None else None,
    }
    return AppError(409, "INTERVAL_OCCUPIED", refusal.message, details)


class TaskPlacementService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        scheduler: ScheduleService,
        on_changed: TaskChangedHandler = task_changed,
    ) -> None:
        self.session = session
        self.clock = clock
        self.scheduler = scheduler
        self.repository = TaskRepository(session)
        self.on_changed = on_changed

    async def pin(self, user_id: UUID, task_id: UUID, body: TaskPinRequest) -> TaskResponse:
        return await self._place(user_id, task_id, body)

    async def move(self, user_id: UUID, task_id: UUID, body: TaskMoveRequest) -> TaskResponse:
        return await self._place(user_id, task_id, body)

    async def _place(
        self, user_id: UUID, task_id: UUID, body: TaskPlacementRequest
    ) -> TaskResponse:
        async with (
            self.session.begin(),
            self.scheduler.task_mutation(
                user_id,
                task_id,
                body.version,
                body.schedule_versions,
                target_date=body.planned_date,
            ) as task,
        ):
            if task.status in {TaskStatus.DONE, TaskStatus.SKIPPED}:
                raise TaskStatusConflictError()
            now = to_utc(self.clock.now())
            try:
                interval = Interval(
                    body.start_at, body.start_at + timedelta(minutes=task.duration_min)
                )
            except OverflowError as exc:
                raise _move_error(
                    "OUTSIDE_SELECTED_DATE", "Интервал выходит за выбранную дату"
                ) from exc
            if await self._validate(user_id, task, body, interval, now):
                return TaskResponse.model_validate(task)
            old_date = task.planned_date
            values = {
                "planned_date": body.planned_date,
                "is_pinned": True,
                "pinned_start": body.start_at,
            }
            changed = frozenset(
                name for name, value in values.items() if getattr(task, name) != value
            )
            task.planned_date = body.planned_date
            task.is_pinned = True
            task.pinned_start = body.start_at
            result, event = await self._save_change(user_id, task, changed, old_date, now)
        await self.on_changed(event)
        return result

    async def unpin(
        self, user_id: UUID, task_id: UUID, version: int, schedule_version: int
    ) -> TaskResponse:
        async with (
            self.session.begin(),
            self.scheduler.task_mutation(user_id, task_id, version, schedule_version) as task,
        ):
            if not task.is_pinned and task.pinned_start is None:
                return TaskResponse.model_validate(task)
            changed = frozenset(
                name
                for name, value in (("is_pinned", False), ("pinned_start", None))
                if getattr(task, name) != value
            )
            task.is_pinned = False
            task.pinned_start = None
            result, event = await self._save_change(
                user_id, task, changed, task.planned_date, to_utc(self.clock.now())
            )
        await self.on_changed(event)
        return result

    async def _save_change(
        self, user_id: UUID, task: Task, changed: frozenset[str], old_date: date, now: datetime
    ) -> tuple[TaskResponse, TaskChanged]:
        task.version += 1
        task.updated_at = now
        flag_modified(task, "updated_at")
        await self.repository.save(task)
        event = TaskChanged(
            user_id, task.id, "updated", changed, old_date, task.planned_date, task.version, now
        )
        try:
            await self.scheduler.task_changed(event)
        except AppError as exc:
            if exc.body.code == "CONFLICT":
                raise _move_error(
                    str(exc.body.details.get("reason_code", "SCHEDULE_CONSTRAINT")),
                    exc.body.message,
                ) from exc
            raise
        await self.session.refresh(task)
        return TaskResponse.model_validate(task), event

    async def _validate(
        self,
        user_id: UUID,
        task: Task,
        body: TaskPlacementRequest,
        interval: Interval,
        now: datetime,
    ) -> bool:
        """Check immutable snapshots before changing any task fields; True denotes a saved pin."""
        days = tuple(sorted({task.planned_date, body.planned_date}))
        active = await self.scheduler.repository.active(user_id, days)
        history = {
            slot.task_id
            for plan in active.values()
            for slot in plan.slots
            if slot.task_id is not None
        }
        rows = await self.scheduler.repository.tasks(user_id, days, history)
        by_id = {row.id: row for row in rows}
        source = saved_slots(active.get(task.planned_date), by_id)
        own = tuple(
            slot for slot in source if slot.task is not None and slot.task.task_id == task.id
        )
        same_pin = (
            task.is_pinned
            and task.planned_date == body.planned_date
            and task.pinned_start == body.start_at
        )
        if same_pin:
            if len(own) != 1 or not own[0].is_pinned or own[0].interval != interval:
                raise AppError(
                    409, "SCHEDULE_RESULT_INCOMPLETE", "Сохранённый результат расписания неполон"
                )
            return True
        if task.actual_start is not None or any(
            slot.interval.start <= now < slot.interval.end for slot in own
        ):
            raise _move_error("TASK_STARTED", "Начатый интервал задачи нельзя изменить")
        if any(slot.interval.end <= now for slot in own):
            raise _move_error(
                "TASK_ALREADY_RESERVED", "Исторический интервал задачи нельзя изменить"
            )
        previous = saved_slots(active.get(body.planned_date), by_id)
        target_history = {slot.task.task_id for slot in previous if slot.task is not None}
        target_rows = [
            row
            for row in rows
            if (row.planned_date == body.planned_date and row.deleted_at is None)
            or row.id in target_history
        ]
        if any(row.id != task.id and row.planned_date != body.planned_date for row in target_rows):
            raise _move_error(
                "TASK_DATE_MISMATCH", "Дата задачи не совпадает с сохранённым расписанием"
            )
        selected = replace(
            task_snapshot(task), planned_date=body.planned_date, is_pinned=False, pinned_start=None
        )
        tasks = (*(task_snapshot(row) for row in target_rows if row.id != task.id), selected)
        profile = profile_snapshot(await self.scheduler.profiles.get_profile(user_id))
        context = PlanContext(profile, body.planned_date, now, tasks, "replan")
        try:
            bounds = make_time_grid(context).day_bounds
            if not bounds.start <= interval.start < interval.end <= bounds.end:
                raise _move_error(
                    "OUTSIDE_SELECTED_DATE",
                    "Интервал выходит за выбранную дату в часовом поясе профиля",
                )
            refusals = selected_placement_refusals(context, selected, interval, previous)
        except ConstraintError as exc:
            raise _move_error(exc.code, str(exc)) from exc
        except PlannerTimeError as exc:
            raise ProfileValidationError(
                "planned_date", exc.code, "Проверьте рабочее время"
            ) from exc
        if refusals:
            refusal = next(
                (item for item in refusals if item.code == "INTERVAL_OCCUPIED"), refusals[0]
            )
            raise _placement_error(refusal)
        return False
