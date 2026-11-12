from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AppError
from app.core.time import Clock, parse_timezone, to_utc
from app.modules.tasks.events import TaskChanged, TaskChangedHandler, TaskOperation, task_changed
from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskCreate, TaskList, TaskListQuery, TaskPatch, TaskResponse
from app.modules.users.repository import ProfileRepository
from app.modules.users.service import ProfileIncompleteError

PLACEMENT_FIELDS = frozenset({"planned_date", "duration_min", "type", "priority", "deadline"})


class TaskNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(404, "TASK_NOT_FOUND", "Задача не найдена")


class TaskVersionConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(409, "TASK_VERSION_CONFLICT", "Задача уже изменена, обновите данные")


class TaskStatusConflictError(AppError):
    def __init__(self) -> None:
        super().__init__(409, "TASK_STATUS_CONFLICT", "Недопустимый переход статуса задачи")


class TaskPinnedError(AppError):
    def __init__(self) -> None:
        super().__init__(409, "TASK_PINNED", "Нельзя изменить размещение закреплённой задачи")


class TaskValidationError(AppError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(
            422,
            "VALIDATION_ERROR",
            "Ошибка проверки данных",
            {"fields": [{"field": f"body.{field}", "code": code, "message": message}]},
        )


def _validate_deadline(planned_date: date, deadline: datetime | None, tz: ZoneInfo) -> None:
    if deadline is not None and deadline.astimezone(tz).date() < planned_date:
        raise TaskValidationError(
            "deadline", "DEADLINE_BEFORE_PLANNED_DATE", "Дедлайн не может быть раньше даты задачи"
        )


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        on_changed: TaskChangedHandler = task_changed,
    ) -> None:
        self.session = session
        self.clock = clock
        self.on_changed = on_changed
        self.repository = TaskRepository(session)
        self.profiles = ProfileRepository(session)

    async def _timezone(self, user_id: UUID) -> ZoneInfo:
        profile = await self.profiles.get(user_id)
        if profile is None:
            raise ProfileIncompleteError()
        try:
            return parse_timezone(profile.timezone)
        except ValueError:
            raise ProfileIncompleteError() from None

    async def get(self, user_id: UUID, task_id: UUID) -> TaskResponse:
        async with self.session.begin():
            task = await self.repository.get(user_id, task_id)
            if task is None:
                raise TaskNotFoundError()
            return TaskResponse.model_validate(task)

    async def list(self, user_id: UUID, query: TaskListQuery) -> TaskList:
        async with self.session.begin():
            items, total = await self.repository.list(user_id, query)
            return TaskList(
                items=[TaskResponse.model_validate(task) for task in items],
                total=total,
                limit=query.limit,
                offset=query.offset,
            )

    async def create(self, user_id: UUID, body: TaskCreate) -> TaskResponse:
        async with self.session.begin():
            tz = await self._timezone(user_id)
            _validate_deadline(body.planned_date, body.deadline, tz)
            now = to_utc(self.clock.now())
            task = Task(user_id=user_id, **body.model_dump(), created_at=now, updated_at=now)
            await self.repository.save(task)
            result = TaskResponse.model_validate(task)
            event = TaskChanged(
                user_id,
                task.id,
                "created",
                frozenset(TaskCreate.model_fields) | {"status"},
                None,
                task.planned_date,
                task.version,
                now,
            )
        await self.on_changed(event)
        return result

    async def patch(self, user_id: UUID, task_id: UUID, body: TaskPatch) -> TaskResponse:
        return await self._change(
            user_id,
            task_id,
            body.version,
            "updated",
            body.model_dump(exclude_unset=True, exclude={"version"}),
        )

    async def delete(self, user_id: UUID, task_id: UUID, version: int) -> None:
        await self._change(user_id, task_id, version, "deleted")

    async def complete(self, user_id: UUID, task_id: UUID, version: int) -> TaskResponse:
        return await self._change(user_id, task_id, version, "completed")

    async def skip(self, user_id: UUID, task_id: UUID, version: int) -> TaskResponse:
        return await self._change(user_id, task_id, version, "skipped")

    async def reopen(self, user_id: UUID, task_id: UUID, version: int) -> TaskResponse:
        return await self._change(user_id, task_id, version, "reopened")

    async def _change(
        self,
        user_id: UUID,
        task_id: UUID,
        version: int,
        operation: TaskOperation,
        values: dict[str, Any] | None = None,
    ) -> TaskResponse:
        async with self.session.begin():
            task = await self.repository.get(user_id, task_id, for_update=True)
            if task is None:
                raise TaskNotFoundError()
            if task.version != version:
                raise TaskVersionConflictError()
            tz = await self._timezone(user_id)
            now = to_utc(self.clock.now())
            if operation == "updated":
                assert values is not None
                changes = {
                    name: value for name, value in values.items() if getattr(task, name) != value
                }
                if task.is_pinned and changes.keys() & PLACEMENT_FIELDS:
                    raise TaskPinnedError()
                _validate_deadline(
                    values.get("planned_date", task.planned_date),
                    values.get("deadline", task.deadline),
                    tz,
                )
                if task.status is TaskStatus.SCHEDULED and changes.keys() & PLACEMENT_FIELDS:
                    changes["status"] = TaskStatus.PENDING
            elif operation == "deleted":
                changes = {"deleted_at": now}
            else:
                values = self._status_values(task, operation, now)
                changes = {
                    name: value for name, value in values.items() if getattr(task, name) != value
                }
            if not changes:
                return TaskResponse.model_validate(task)
            old_date = task.planned_date
            for name, value in changes.items():
                setattr(task, name, value)
            task.version += 1
            task.updated_at = now
            flag_modified(task, "updated_at")
            await self.repository.save(task)
            result = TaskResponse.model_validate(task)
            event = TaskChanged(
                user_id,
                task.id,
                operation,
                frozenset(changes),
                old_date,
                None if operation == "deleted" else task.planned_date,
                task.version,
                now,
            )
        await self.on_changed(event)
        return result

    @staticmethod
    def _status_values(task: Task, operation: TaskOperation, now: datetime) -> dict[str, Any]:
        target = {
            "completed": TaskStatus.DONE,
            "skipped": TaskStatus.SKIPPED,
            "reopened": TaskStatus.PENDING,
        }[operation]
        if task.status is target:
            return {}
        allowed = (
            {TaskStatus.DONE, TaskStatus.SKIPPED}
            if operation == "reopened"
            else {TaskStatus.PENDING, TaskStatus.SCHEDULED}
        )
        if task.status not in allowed:
            raise TaskStatusConflictError()
        values: dict[str, Any] = {
            "status": target,
            "completed_at": now if target is TaskStatus.DONE else None,
        }
        if operation == "reopened":
            values.update(actual_start=None, actual_end=None)
        return values
