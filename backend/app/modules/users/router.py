from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.private_api import PrivateAPIRoute
from app.core.security import get_current_user
from app.modules.schedule.dependencies import get_profile_scheduler
from app.modules.users.dependencies import get_profile_changed_handler, get_profile_service
from app.modules.users.events import ProfileChangedHandler
from app.modules.users.models import User
from app.modules.users.schemas import ProfileDocument, ProfilePatch
from app.modules.users.service import ProfileService

router = APIRouter(tags=["profile"], route_class=PrivateAPIRoute)

CurrentUser = Annotated[User, Depends(get_current_user)]
Profiles = Annotated[ProfileService, Depends(get_profile_service)]


@router.get("/me", response_model=ProfileDocument, summary="Пользователь и состояние настройки")
async def get_me(user: CurrentUser, service: Profiles) -> ProfileDocument:
    """Доступен до завершения онбординга; отсутствующий профиль возвращается как null."""
    return await service.get_document(user.id)


@router.patch("/me/profile", response_model=ProfileDocument, summary="Частичное изменение профиля")
async def patch_profile(
    body: ProfilePatch,
    user: CurrentUser,
    service: Profiles,
    on_changed: Annotated[ProfileChangedHandler, Depends(get_profile_changed_handler)],
    before_commit: Annotated[ProfileChangedHandler, Depends(get_profile_scheduler)],
) -> ProfileDocument:
    """Сохраняет только переданные поля и возвращает полный актуальный документ.

    Время — HH:mm:00, дата — YYYY-MM-DD, timezone — IANA. Не завершает онбординг.
    Обязательные данные завершённого профиля нельзя очистить (409 PROFILE_INCOMPLETE).
    """
    return await service.patch_document(user.id, body, on_changed, before_commit)
