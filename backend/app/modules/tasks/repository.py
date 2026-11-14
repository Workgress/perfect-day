from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskListQuery


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, task_id: UUID, *, for_update: bool = False) -> Task | None:
        statement = (
            select(Task)
            .where(Task.id == task_id, Task.user_id == user_id, Task.deleted_at.is_(None))
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list(self, user_id: UUID, query: TaskListQuery) -> tuple[list[Task], int]:
        statement = select(Task).where(Task.user_id == user_id, Task.deleted_at.is_(None))
        if query.date is not None:
            statement = statement.where(Task.planned_date == query.date)
        if query.from_date is not None:
            statement = statement.where(Task.planned_date >= query.from_date)
        if query.to_date is not None:
            statement = statement.where(Task.planned_date <= query.to_date)
        if query.status is not None:
            statement = statement.where(Task.status == query.status)
        if query.type is not None:
            statement = statement.where(Task.type == query.type)

        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        result = await self.session.scalars(
            statement.order_by(Task.planned_date, Task.created_at, Task.id)
            .limit(query.limit)
            .offset(query.offset)
            .execution_options(populate_existing=True)
        )
        return list(result), total if total is not None else 0

    async def save(self, task: Task) -> None:
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
