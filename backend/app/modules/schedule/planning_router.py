from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import AppError
from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.schedule.dependencies import get_schedule_reader, get_schedule_service
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.planning_schemas import (
    PlacementCheckRequest,
    PlacementCheckResponse,
    PlacementInterval,
    SchedulePlacementChange,
    SchedulePlanningDetails,
    ScheduleReplanRequest,
    ScheduleReplanResponse,
)
from app.modules.schedule.read_router import ScheduleReadQuery, get_schedule_read_query
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import User
from app.modules.users.repository import ProfileRepository

router = APIRouter(prefix="/schedule", tags=["schedule"], route_class=PrivateAPIRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Scheduler = Annotated[ScheduleService, Depends(get_schedule_service)]
Reader = Annotated[ScheduleReader, Depends(get_schedule_reader)]
DateQuery = Annotated[ScheduleReadQuery, Depends(get_schedule_read_query)]


@router.get(
    "/details",
    response_model=SchedulePlanningDetails,
    summary="Прочитать расписание с рекомендациями и пояснениями",
    description=(
        "Одна сохранённая версия: расписание, рекомендации с task_id и обеими датами, "
        "пояснения размещённых и неразмещённых задач для панели и карточки ближайшей задачи. "
        "Чтение не запускает расчёт и не изменяет данные. Рекомендация проверена на момент "
        "генерации плана и не резервирует время. Применение переноса — отдельное изменение "
        "planned_date через PATCH /tasks/{task_id} с актуальной version и повторным расчётом. "
        "Ошибки: 404 SCHEDULE_NOT_FOUND, 409 ONBOARDING_REQUIRED, "
        "409 SCHEDULE_RESULT_INCOMPLETE, 422 VALIDATION_ERROR. Cache-Control: no-store."
    ),
)
async def read_details(
    user: CurrentUser, reader: Reader, query: DateQuery
) -> SchedulePlanningDetails:
    async with reader.session.begin():
        profile = await ProfileRepository(reader.session).get(user.id)
        if profile is None or profile.onboarding_completed_at is None:
            raise AppError(409, "ONBOARDING_REQUIRED", "Сначала завершите настройку профиля")
        result = await reader.get_details(user.id, query.date)
        if result is None:
            raise AppError(404, "SCHEDULE_NOT_FOUND", "Расписание не найдено")
        return result


@router.post(
    "/check-placement",
    response_model=PlacementCheckResponse,
    summary="Проверить выбранный интервал без сохранения",
    description=(
        "Проверяет собственную задачу с актуальной version по текущему профилю и расписанию. "
        "Отказ размещения — 200 с allowed=false и причинами, включая время пересечения "
        "и conflicting_task_id. Проверка не резервирует интервал, не сохраняет время "
        "и должна повторяться при сохранении. Даты локальные в поясе профиля, "
        "start_at/end_at — ISO 8601 с явным смещением; ответ нормализован в UTC. "
        "Ошибки: 404 TASK_NOT_FOUND, 409 TASK_VERSION_CONFLICT, 409 ONBOARDING_REQUIRED, "
        "409 PROFILE_INCOMPLETE, 409 CONFLICT, 422 VALIDATION_ERROR. Cache-Control: no-store."
    ),
)
async def check_placement(
    body: PlacementCheckRequest, user: CurrentUser, service: Scheduler
) -> PlacementCheckResponse:
    async with service.session.begin():
        return await service.check_placement(user.id, body)


@router.post(
    "/replan",
    response_model=ScheduleReplanResponse,
    summary="Пересчитать и сохранить расписание",
    description=(
        "Строит новую сохранённую версию вокруг закреплённых и начатых интервалов. "
        "allow_date_change=false по умолчанию: неразмещённая задача сохраняет дату, "
        "остаётся без времени и получает объяснение. Только явное true разрешает "
        "автоматические переносы; они возвращаются в schedule.moves, а рекомендации "
        "не перемещают задачи. Изменения задач и всех затронутых планов атомарны. "
        "Ответ содержит сохранённое расписание, рекомендации, пояснения и changes "
        "с исходными и итоговыми UTC-интервалами. Каждый вызов создаёт новую версию плана; "
        "при потере ответа сначала перечитайте /schedule/details. "
        "Ошибки: 409 ONBOARDING_REQUIRED, 409 PROFILE_INCOMPLETE, 409 CONFLICT, "
        "409 SCHEDULE_RESULT_INCOMPLETE, 422 VALIDATION_ERROR, 503 PLANNER_UNAVAILABLE. "
        "Cache-Control: no-store."
    ),
)
async def replan(
    body: ScheduleReplanRequest, user: CurrentUser, service: Scheduler
) -> ScheduleReplanResponse:
    async with service.session.begin():
        result = await service.replan(
            user.id,
            body.planned_date,
            ScheduleTrigger.MANUAL_EDIT,
            allow_date_change=body.allow_date_change,
        )
        details = await ScheduleReader(service.session).get_details(user.id, body.planned_date)
        if details is None:
            raise AppError(
                409, "SCHEDULE_RESULT_INCOMPLETE", "Сохранённый результат расписания неполон"
            )
        changes = []
        for item in result.changes:
            assert item.task.task_id is not None
            changes.append(
                SchedulePlacementChange(
                    task_id=item.task.task_id,
                    kind=item.kind,
                    reason_codes=item.reason_codes,
                    before=PlacementInterval(
                        start_at=item.before.interval.start, end_at=item.before.interval.end
                    )
                    if item.before
                    else None,
                    after=PlacementInterval(
                        start_at=item.after.interval.start, end_at=item.after.interval.end
                    )
                    if item.after
                    else None,
                )
            )
        return ScheduleReplanResponse(**details.model_dump(), changes=tuple(changes))
