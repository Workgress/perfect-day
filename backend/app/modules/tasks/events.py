from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

TaskOperation = Literal["created", "updated", "deleted", "completed", "skipped", "reopened"]


@dataclass(frozen=True)
class TaskChanged:
    user_id: UUID
    task_id: UUID
    operation: TaskOperation
    changed_fields: frozenset[str]
    old_planned_date: date | None
    new_planned_date: date | None
    version: int
    occurred_at: datetime


class TaskChangedHandler(Protocol):
    async def __call__(self, event: TaskChanged) -> None: ...


async def task_changed(event: TaskChanged) -> None:
    pass
