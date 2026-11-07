from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.biorhythm.dependencies import get_biorhythm_service
from app.modules.biorhythm.schemas import (
    CriticalDaysQuery,
    ForecastQuery,
    SeriesQuery,
    SnapshotQuery,
)
from app.modules.biorhythm.service import BiorhythmService
from app.modules.biorhythm.types import BiorhythmSnapshot, CriticalDays, Forecast
from app.modules.users.models import User

router = APIRouter(
    prefix="/biorhythms",
    tags=["biorhythms"],
    route_class=PrivateAPIRoute,
)

CurrentUser = Annotated[User, Depends(get_current_user)]
Biorhythms = Annotated[BiorhythmService, Depends(get_biorhythm_service)]


@router.get("/now", response_model=BiorhythmSnapshot, summary="Текущие значения биоритмов")
async def get_now(
    user: CurrentUser, service: Biorhythms, query: Annotated[SnapshotQuery, Query()]
) -> BiorhythmSnapshot:
    """Расчёт на указанный момент или сейчас. at должен содержать часовой пояс.

    Возвращает три цикла, фазы, направления и критичность локального дня.
    Требует завершённого онбординга (409 ONBOARDING_REQUIRED).
    """
    return await service.get_snapshot(user.id, query.at)


@router.get("", response_model=Forecast, summary="Ряд значений для графика")
async def get_series(
    user: CurrentUser, service: Biorhythms, query: Annotated[SeriesQuery, Query()]
) -> Forecast:
    """Локальные даты from/to включительны; диапазон от 1 до 62 дней.

    Суточный шаг использует локальный полдень, часовой учитывает переходы DST.
    Требует завершённого онбординга (409 ONBOARDING_REQUIRED).
    """
    return await service.get_series(user.id, query.start, query.end, query.step)


@router.get(
    "/critical-days", response_model=CriticalDays, summary="Критические дни и пересечения нуля"
)
async def get_critical_days(
    user: CurrentUser, service: Biorhythms, query: Annotated[CriticalDaysQuery, Query()]
) -> CriticalDays:
    """Локальные даты from/to включительны; диапазон от 1 до 62 дней.

    Только критические дни; моменты пересечений возвращаются в UTC.
    Требует завершённого онбординга (409 ONBOARDING_REQUIRED).
    """
    return await service.get_critical_days(user.id, query.start, query.end)


@router.get("/forecast", response_model=Forecast, summary="Прогноз на день, неделю или месяц")
async def get_forecast(
    user: CurrentUser, service: Biorhythms, query: Annotated[ForecastQuery, Query()]
) -> Forecast:
    """Начинается с текущего локального дня. day — часовой шаг, week/month — суточный.

    Требует завершённого онбординга (409 ONBOARDING_REQUIRED).
    """
    return await service.get_forecast(user.id, query.period)
