from dataclasses import dataclass
from datetime import datetime, time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock, LocalTimeError, local_to_utc, parse_timezone, to_utc
from app.modules.users.models import ChronotypeSource, UserProfile
from app.modules.users.repository import ProfileRepository
from app.modules.users.schemas import ProfileFields, ProfilePatch, ProfileResponse


class ProfileValidationError(ValueError):
    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code


class ProfileUserNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class ProfileUpdate:
    profile: ProfileResponse
    changed_fields: frozenset[str]


def _normalize_birth(
    state: ProfileFields, previous: ProfileFields, patch: ProfilePatch, now: datetime
) -> datetime | None:
    if state.birth_date is not None and state.birth_tz is None:
        state.birth_tz = state.timezone

    if not state.birth_time_known:
        if "birth_time" in patch.model_fields_set and patch.birth_time not in (None, time(12)):
            raise ProfileValidationError(
                "birth_time", "UNKNOWN_BIRTH_TIME", "Для неизвестного времени используется 12:00"
            )
        state.birth_time = time(12)
    elif not previous.birth_time_known and (
        "birth_time" not in patch.model_fields_set or patch.birth_time is None
    ):
        raise ProfileValidationError(
            "birth_time", "BIRTH_TIME_REQUIRED", "Укажите известное время рождения"
        )

    if state.birth_date is None:
        return None
    assert state.birth_tz is not None
    tz = parse_timezone(state.birth_tz)
    if state.birth_date > now.astimezone(tz).date():
        raise ProfileValidationError(
            "birth_date", "BIRTH_IN_FUTURE", "Дата рождения не может быть в будущем"
        )
    if state.birth_time is None:
        return None
    try:
        birth_utc = local_to_utc(datetime.combine(state.birth_date, state.birth_time), tz)
    except LocalTimeError as exc:
        code = exc.code.replace("LOCAL_TIME", "BIRTH_TIME")
        raise ProfileValidationError("birth_time", code, str(exc)) from exc
    if birth_utc > now:
        raise ProfileValidationError(
            "birth_time", "BIRTH_IN_FUTURE", "Момент рождения не может быть в будущем"
        )
    return birth_utc


def _validate_day_settings(state: ProfileFields) -> None:
    if state.wake_time == state.sleep_time:
        raise ProfileValidationError(
            "sleep_time", "SLEEP_WINDOW_INVALID", "Время сна и пробуждения должны различаться"
        )
    if state.work_end <= state.work_start:
        raise ProfileValidationError(
            "work_end", "WORK_WINDOW_INVALID", "Конец рабочего дня должен быть позже начала"
        )


class ProfileService:
    """The caller owns the outer transaction and commits after successful use.

    A savepoint makes a failed profile update atomic without committing or
    rolling back unrelated work, including a prior current_user query.
    """

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.repository = ProfileRepository(session)
        self.clock = clock

    async def get_profile(self, user_id: UUID) -> ProfileResponse | None:
        profile = await self.repository.get(user_id)
        return ProfileResponse.model_validate(profile) if profile is not None else None

    async def update_profile(self, user_id: UUID, patch: ProfilePatch) -> ProfileUpdate:
        async with self.session.begin_nested():
            if not await self.repository.lock_user(user_id):
                raise ProfileUserNotFoundError("Пользователь не найден")
            profile = await self.repository.get(user_id)
            previous = ProfileFields.model_validate(profile) if profile else ProfileFields()
            state = ProfileFields.model_validate(
                previous.model_dump() | patch.model_dump(exclude_unset=True)
            )
            _validate_day_settings(state)
            birth_utc = _normalize_birth(state, previous, patch, to_utc(self.clock.now()))
            if (
                profile is not None
                and profile.onboarding_completed_at is not None
                and (birth_utc is None or state.chronotype is None)
            ):
                raise ProfileValidationError(
                    "profile",
                    "ONBOARDING_DATA_REQUIRED",
                    "Нельзя очистить обязательные данные профиля",
                )

            values = state.model_dump() | {"birth_at_utc": birth_utc}
            if "chronotype" in patch.model_fields_set:
                values["chronotype_source"] = (
                    ChronotypeSource.MANUAL if state.chronotype is not None else None
                )
            changed_fields = frozenset(
                name
                for name, value in values.items()
                if profile is None or getattr(profile, name) != value
            )
            if profile is None:
                profile = UserProfile(user_id=user_id, **values)
            else:
                for name in changed_fields:
                    setattr(profile, name, values[name])
            await self.repository.save(profile)
            return ProfileUpdate(ProfileResponse.model_validate(profile), changed_fields)
