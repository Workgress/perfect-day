from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.schedule.dependencies import get_schedule_reader
from app.modules.schedule.read_models import ScheduleReadResult
from app.modules.schedule.reader import ScheduleReader
from app.modules.tasks.schemas import TaskDate
from app.modules.users.models import User
from app.modules.users.repository import ProfileRepository

router = APIRouter(prefix="/schedule", tags=["schedule"], route_class=PrivateAPIRoute)


class ScheduleReadQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: TaskDate = Field(description="Локальная дата расписания в формате YYYY-MM-DD")


def get_schedule_read_query(
    request: Request, query: Annotated[ScheduleReadQuery, Query()]
) -> ScheduleReadQuery:
    if len(request.query_params.getlist("date")) > 1:
        raise RequestValidationError(
            [{"loc": ("query", "date"), "type": "value_error", "msg": "Параметр повторяется"}]
        )
    return query


@router.get(
    "",
    response_model=ScheduleReadResult,
    summary="Прочитать сохранённое расписание на день",
    description=(
        "Возвращает активную сохранённую версию в её часовом поясе, без генерации и пересчёта. "
        "Дата обязательна. День без задач возвращается как обычный план, включая системные "
        "интервалы. Ошибки: 404 SCHEDULE_NOT_FOUND, 409 ONBOARDING_REQUIRED, "
        "409 SCHEDULE_RESULT_INCOMPLETE, 422 VALIDATION_ERROR. "
        "Все ответы: Cache-Control: no-store."
    ),
)
async def read_schedule(
    user: Annotated[User, Depends(get_current_user)],
    reader: Annotated[ScheduleReader, Depends(get_schedule_reader)],
    query: Annotated[ScheduleReadQuery, Depends(get_schedule_read_query)],
) -> ScheduleReadResult:
    async with reader.session.begin():
        profile = await ProfileRepository(reader.session).get(user.id)
        if profile is None or profile.onboarding_completed_at is None:
            raise AppError(409, "ONBOARDING_REQUIRED", "Сначала завершите настройку профиля")
        result = await reader.get(user.id, query.date)
        if result is None:
            raise AppError(404, "SCHEDULE_NOT_FOUND", "Расписание не найдено")
        return result
