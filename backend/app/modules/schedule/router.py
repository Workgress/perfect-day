from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.schedule.dependencies import get_schedule_service
from app.modules.schedule.schemas import OnboardingRequest, PlanPreview
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import User
from app.modules.users.schemas import ProfileDocument

router = APIRouter(prefix="/onboarding", tags=["onboarding"], route_class=PrivateAPIRoute)
CurrentUser = Annotated[User, Depends(get_current_user)]
Scheduler = Annotated[ScheduleService, Depends(get_schedule_service)]


@router.post("/preview", response_model=PlanPreview, summary="Предпросмотр плана без сохранения")
async def preview(body: OnboardingRequest, user: CurrentUser, service: Scheduler) -> PlanPreview:
    """Только расчёт: задачи и план не сохраняются. Частичный результат допустим.

    Индексы соответствуют исходному массиву, время — местное HH:mm:00.
    Ошибки: PROFILE_INCOMPLETE, PLANNED_DATE_CHANGED, VALIDATION_ERROR,
    PLANNER_UNAVAILABLE. Ответ всегда Cache-Control: no-store.
    """
    async with service.session.begin():
        return await service.preview(user.id, body)


@router.post("/complete", response_model=ProfileDocument, summary="Атомарное завершение настройки")
async def complete(
    body: OnboardingRequest,
    user: CurrentUser,
    service: Scheduler,
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ProfileDocument:
    """Одна транзакция: первые задачи, полный план, завершение и запись успешного повтора.

    Тот же ключ и исходное тело возвращают сохранённый ответ, включая после смены даты.
    Ошибки: IDEMPOTENCY_CONFLICT, ONBOARDING_ALREADY_COMPLETED, PROFILE_INCOMPLETE,
    PLANNED_DATE_CHANGED, PLAN_CAPACITY_EXCEEDED, VALIDATION_ERROR, PLANNER_UNAVAILABLE.
    Частичный план не завершает настройку. Полный CRUD задач в этот метод не входит.
    """
    async with service.session.begin():
        return await service.complete(user.id, key, body)
