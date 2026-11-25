from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.tasks.dependencies import (
    get_task_delete_query,
    get_task_list_query,
    get_task_placement_service,
    get_task_service,
    get_task_unpin_query,
)
from app.modules.tasks.placement_schemas import (
    TaskMoveRequest,
    TaskPinRequest,
    TaskStartNowRequest,
    TaskUnpinQuery,
)
from app.modules.tasks.placement_service import TaskPlacementService
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
Placement = Annotated[TaskPlacementService, Depends(get_task_placement_service)]


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


@router.post(
    "/{task_id}/pin",
    response_model=TaskResponse,
    summary="Закрепить задачу на выбранных дате и времени",
    description=(
        "Принимает версию задачи и schedule_versions исходного и целевого дней. "
        "Версия 0 означает отсутствие плана. Дата локальная в поясе профиля. "
        "start_at — ISO 8601 с UTC-смещением; конец вычисляет сервер. "
        "Проверка интервала и сохранение задачи с пересчётом обоих дней атомарны. "
        "Закреплённое будущее время можно заменить; занятое время и история не перемещаются. "
        "Тот же pin с актуальными версиями не меняет задачу и план. "
        "Ошибки: 404 TASK_NOT_FOUND, 409 TASK_VERSION_CONFLICT, 409 SCHEDULE_VERSION_CONFLICT, "
        "409 TASK_STATUS_CONFLICT, 409 INTERVAL_OCCUPIED, 409 TASK_MOVE_NOT_ALLOWED, "
        "409 ONBOARDING_REQUIRED, 409 PROFILE_INCOMPLETE, 409 SCHEDULE_RESULT_INCOMPLETE, "
        "422 VALIDATION_ERROR, 503 PLANNER_UNAVAILABLE. Cache-Control: no-store."
    ),
)
async def pin_task(
    task_id: UUID, body: TaskPinRequest, user: CurrentUser, service: Placement
) -> TaskResponse:
    return await service.pin(user.id, task_id, body)


@router.post(
    "/{task_id}/move",
    response_model=TaskResponse,
    summary="Переместить и закрепить задачу",
    description=(
        "Общая операция для формы и перетаскивания: planned_date — локальная дата профиля, "
        "start_at — ISO 8601 с UTC-смещением. Конец вычисляется по длительности задачи. "
        "Обязательны version задачи и schedule_versions обоих затронутых дней; "
        "в пределах дня нужен один ключ, 0 означает отсутствие плана. "
        "Перемещение закрепляет время; прежнее будущее закрепление можно заменить. "
        "Фиксация даты сохраняется и не запрещает явный ручной перенос. "
        "Занятое время, начатые и исторические интервалы не перемещаются. "
        "Изменение задачи и пересчёт обоих дней атомарны. Повтор с актуальными версиями "
        "и тем же размещением не меняет задачу, расписания и версии. "
        "Ошибки: 404 TASK_NOT_FOUND, 409 TASK_VERSION_CONFLICT, 409 SCHEDULE_VERSION_CONFLICT, "
        "409 TASK_STATUS_CONFLICT, 409 INTERVAL_OCCUPIED, 409 TASK_MOVE_NOT_ALLOWED, "
        "409 ONBOARDING_REQUIRED, 409 PROFILE_INCOMPLETE, 409 SCHEDULE_RESULT_INCOMPLETE, "
        "422 VALIDATION_ERROR, 503 PLANNER_UNAVAILABLE. Cache-Control: no-store."
    ),
)
async def move_task(
    task_id: UUID, body: TaskMoveRequest, user: CurrentUser, service: Placement
) -> TaskResponse:
    return await service.move(user.id, task_id, body)


@router.post(
    "/{task_id}/start-now",
    response_model=TaskResponse,
    summary="Начать задачу сейчас и пересчитать день",
    description=(
        "Принимает version задачи и schedule_versions её текущего дня. "
        "Задача должна быть активной и относиться к сегодняшней дате в поясе профиля. "
        "Сервер один раз получает время, сохраняет actual_start и полный интервал от now. "
        "Прежний будущий слот заменяется; история и чужие занятые интервалы не перемещаются. "
        "Фиксация даты сохраняется; у закреплённой задачи pinned_start обновляется до now. "
        "Задача, план и запись пересчёта сохраняются атомарно. Повтор для начатой задачи "
        "с актуальными версиями возвращает исходное actual_start без изменений. "
        "Ошибки: 404 TASK_NOT_FOUND, 409 TASK_VERSION_CONFLICT, 409 SCHEDULE_VERSION_CONFLICT, "
        "409 TASK_STATUS_CONFLICT, 409 TASK_MOVE_NOT_ALLOWED, 409 INTERVAL_OCCUPIED, "
        "409 ONBOARDING_REQUIRED, 409 PROFILE_INCOMPLETE, 409 SCHEDULE_RESULT_INCOMPLETE, "
        "422 VALIDATION_ERROR, 503 PLANNER_UNAVAILABLE. Cache-Control: no-store."
    ),
)
async def start_task_now(
    task_id: UUID, body: TaskStartNowRequest, user: CurrentUser, service: Placement
) -> TaskResponse:
    return await service.start_now(user.id, task_id, body)


@router.delete(
    "/{task_id}/pin",
    response_model=TaskResponse,
    summary="Открепить задачу и пересчитать расписание",
    description=(
        "Query version — версия задачи, schedule_version — версия плана текущей даты задачи. "
        "Версия плана 0 означает его отсутствие. Обе версии проверяются до любых изменений. "
        "Снятие фиксации времени и пересчёт дня атомарны; дата задачи не меняется. "
        "Фиксация даты и фактическое начало сохраняются, начатые и исторические интервалы "
        "остаются на месте. Если фиксация уже снята, актуальные версии возвращают задачу "
        "без изменения времени, версий и расписания. Ответ — 200 TaskResponse. "
        "Ошибки: 404 TASK_NOT_FOUND, 409 TASK_VERSION_CONFLICT, 409 SCHEDULE_VERSION_CONFLICT, "
        "409 TASK_MOVE_NOT_ALLOWED, 409 ONBOARDING_REQUIRED, 409 PROFILE_INCOMPLETE, "
        "422 VALIDATION_ERROR, 503 PLANNER_UNAVAILABLE. Cache-Control: no-store."
    ),
)
async def unpin_task(
    task_id: UUID,
    user: CurrentUser,
    service: Placement,
    query: Annotated[TaskUnpinQuery, Depends(get_task_unpin_query)],
) -> TaskResponse:
    return await service.unpin(user.id, task_id, query.version, query.schedule_version)


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
