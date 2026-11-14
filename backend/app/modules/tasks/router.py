from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.tasks.dependencies import (
    get_task_delete_query,
    get_task_list_query,
    get_task_service,
)
from app.modules.tasks.schemas import (
    TaskCreate,
    TaskDeleteQuery,
    TaskList,
    TaskListQuery,
    TaskPatch,
    TaskResponse,
    TaskStatusCommand,
)
from app.modules.tasks.service import TaskService
from app.modules.users.models import User

router = APIRouter(prefix="/tasks", tags=["tasks"], route_class=PrivateAPIRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Tasks = Annotated[TaskService, Depends(get_task_service)]


@router.post("", status_code=201, response_model=TaskResponse, summary="Создать задачу")
async def create_task(body: TaskCreate, user: CurrentUser, service: Tasks) -> TaskResponse:
    return await service.create(user.id, body)


@router.get("", response_model=TaskList, summary="Список задач")
async def list_tasks(
    user: CurrentUser,
    service: Tasks,
    query: Annotated[TaskListQuery, Depends(get_task_list_query)],
) -> TaskList:
    return await service.list(user.id, query)


@router.get("/{task_id}", response_model=TaskResponse, summary="Получить задачу")
async def get_task(task_id: UUID, user: CurrentUser, service: Tasks) -> TaskResponse:
    return await service.get(user.id, task_id)


@router.patch("/{task_id}", response_model=TaskResponse, summary="Изменить задачу или дату")
async def patch_task(
    task_id: UUID, body: TaskPatch, user: CurrentUser, service: Tasks
) -> TaskResponse:
    return await service.patch(user.id, task_id, body)


@router.delete("/{task_id}", status_code=204, response_class=Response, summary="Удалить задачу")
async def delete_task(
    task_id: UUID,
    user: CurrentUser,
    service: Tasks,
    query: Annotated[TaskDeleteQuery, Depends(get_task_delete_query)],
) -> Response:
    await service.delete(user.id, task_id, query.version)
    return Response(status_code=204)


@router.post("/{task_id}/complete", response_model=TaskResponse, summary="Выполнить задачу")
async def complete_task(
    task_id: UUID, body: TaskStatusCommand, user: CurrentUser, service: Tasks
) -> TaskResponse:
    return await service.complete(user.id, task_id, body.version)


@router.post("/{task_id}/skip", response_model=TaskResponse, summary="Пропустить задачу")
async def skip_task(
    task_id: UUID, body: TaskStatusCommand, user: CurrentUser, service: Tasks
) -> TaskResponse:
    return await service.skip(user.id, task_id, body.version)


@router.post("/{task_id}/reopen", response_model=TaskResponse, summary="Вернуть задачу в работу")
async def reopen_task(
    task_id: UUID, body: TaskStatusCommand, user: CurrentUser, service: Tasks
) -> TaskResponse:
    return await service.reopen(user.id, task_id, body.version)
