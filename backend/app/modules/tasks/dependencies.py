from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock
from app.db.session import get_session
from app.modules.tasks.events import TaskChangedHandler, task_changed
from app.modules.tasks.schemas import TaskDeleteQuery, TaskListQuery
from app.modules.tasks.service import TaskService
from app.modules.users.dependencies import get_clock


def get_task_changed_handler() -> TaskChangedHandler:
    return task_changed


def get_task_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
    handler: Annotated[TaskChangedHandler, Depends(get_task_changed_handler)],
) -> TaskService:
    return TaskService(session, clock, handler)


def _reject_duplicate_parameters(request: Request) -> None:
    for name in request.query_params:
        if len(request.query_params.getlist(name)) > 1:
            raise RequestValidationError(
                [{"loc": ("query", name), "type": "value_error", "msg": "Параметр повторяется"}]
            )


def get_task_list_query(
    request: Request, query: Annotated[TaskListQuery, Query()]
) -> TaskListQuery:
    _reject_duplicate_parameters(request)
    return query


def get_task_delete_query(
    request: Request, query: Annotated[TaskDeleteQuery, Query()]
) -> TaskDeleteQuery:
    _reject_duplicate_parameters(request)
    return query
