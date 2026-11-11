from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock, SystemClock
from app.db.session import get_session
from app.modules.users.events import ProfileChangedHandler, profile_changed
from app.modules.users.service import ProfileService


def get_clock() -> Clock:
    return SystemClock()


def get_profile_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ProfileService:
    return ProfileService(session, clock)


def get_profile_changed_handler() -> ProfileChangedHandler:
    return profile_changed
