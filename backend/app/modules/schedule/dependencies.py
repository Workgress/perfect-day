from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock
from app.db.session import get_session
from app.modules.schedule.service import ScheduleService
from app.modules.users.dependencies import get_clock
from app.modules.users.events import ProfileChangedHandler


def get_schedule_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ScheduleService:
    return ScheduleService(session, clock)


def get_profile_scheduler(
    service: Annotated[ScheduleService, Depends(get_schedule_service)],
) -> ProfileChangedHandler:
    return service.profile_changed
