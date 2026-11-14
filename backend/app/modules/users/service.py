from dataclasses import dataclass
from datetime import UTC, datetime, time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import Clock, parse_timezone, to_utc
from app.modules.users.events import ProfileChanged, ProfileChangedHandler
from app.modules.users.models import ChronotypeSource, User, UserProfile
from app.modules.users.repository import ProfileRepository
from app.modules.users.schemas import (
    OnboardingProgress,
    ProfileDocument,
    ProfileFields,
    ProfilePatch,
    ProfileResponse,
    ProfileState,
)


class ProfileValidationError(AppError):
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        super().__init__(
            422,
            "VALIDATION_ERROR",
            "Ошибка проверки данных",
            {"fields": [{"field": f"body.{field}", "code": code, "message": message}]},
        )


class ProfileIncompleteError(AppError):
    def __init__(self) -> None:
        super().__init__(409, "PROFILE_INCOMPLETE", "Заполните обязательные данные профиля")


class ProfileUserNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(401, "AUTHENTICATION_REQUIRED", "Необходима аутентификация")


@dataclass(frozen=True)
class ProfileUpdate:
    profile: ProfileState
    changed_fields: frozenset[str]
    document: ProfileDocument


def _normalize_birth(state: ProfileFields) -> datetime | None:
    """Use the v1 UTC computational scale, not a historical birthplace zone.

    Reads canonicalize old data without writes; the next successful PATCH
    persists this normalized state, preserving the current user timezone.
    """
    state.birth_tz = "UTC"
    state.birth_time_known = state.birth_time_known and state.birth_time is not None
    if not state.birth_time_known:
        state.birth_time = time(12)
    elif state.birth_time is not None:
        state.birth_time = state.birth_time.replace(second=0, microsecond=0)
    if state.birth_date is None:
        return None
    assert state.birth_time is not None
    return datetime.combine(state.birth_date, state.birth_time, UTC)


def _read_state(profile: UserProfile) -> ProfileState:
    state = ProfileState.model_validate(profile)
    # Earlier versions accepted seconds; v1 DTOs and UI work in whole minutes.
    for name in ("work_start", "work_end", "sleep_time"):
        setattr(state, name, getattr(state, name).replace(second=0, microsecond=0))
    state.birth_at_utc = _normalize_birth(state)
    return state


def _valid_regime(state: ProfileFields) -> bool:
    return state.work_end > state.work_start and all(
        value.second == 0 and value.microsecond == 0
        for value in (state.work_start, state.work_end, state.sleep_time)
    )


def _document(user: User, state: ProfileState | None) -> ProfileDocument:
    public_profile = None
    step: str | None = "birth_date"
    completed_at = None
    if state is not None:
        public_profile = ProfileResponse(
            birth_date=state.birth_date,
            birth_time=state.birth_time if state.birth_time_known else None,
            timezone=state.timezone,
            chronotype=state.chronotype,
            work_start=state.work_start,
            work_end=state.work_end,
            sleep_time=state.sleep_time,
        )
        if state.birth_date is None:
            step = "birth_date"
        elif state.chronotype is None or not _valid_regime(state):
            step = "chronotype"
        elif state.onboarding_completed_at is None:
            step = "first_tasks"
        else:
            completed_at = state.onboarding_completed_at
            step = None
        if state.onboarding_completed_at is not None and step is not None:
            raise ProfileIncompleteError()
    return ProfileDocument(
        id=user.id,
        email=user.email,
        display_name=state.display_name if state else None,
        profile=public_profile,
        onboarding=OnboardingProgress.model_validate(
            {"completed_at": completed_at, "next_step": step}
        ),
    )


class ProfileService:
    """The caller owns the outer transaction; failed updates use a savepoint."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self.session = session
        self.repository = ProfileRepository(session)
        self.clock = clock

    async def get_profile(self, user_id: UUID) -> ProfileState | None:
        """Internal normalized calculation context, never a public DTO."""
        profile = await self.repository.get(user_id)
        return _read_state(profile) if profile is not None else None

    async def get_document(self, user_id: UUID) -> ProfileDocument:
        user = await self.repository.get_user(user_id)
        if user is None:
            raise ProfileUserNotFoundError()
        return _document(user, await self.get_profile(user_id))

    async def patch_document(
        self,
        user_id: UUID,
        patch: ProfilePatch,
        on_changed: ProfileChangedHandler,
        before_commit: ProfileChangedHandler | None = None,
    ) -> ProfileDocument:
        """Replan atomically through before_commit, then dispatch post-commit notifications."""
        async with self.session.begin():
            result = await self.update_profile(user_id, patch)
            if result.changed_fields and before_commit is not None:
                await before_commit(
                    ProfileChanged(user_id, result.changed_fields, to_utc(self.clock.now()))
                )
        if result.changed_fields:
            await on_changed(
                ProfileChanged(user_id, result.changed_fields, to_utc(self.clock.now()))
            )
        return result.document

    async def update_profile(self, user_id: UUID, patch: ProfilePatch) -> ProfileUpdate:
        async with self.session.begin_nested():
            user = await self.repository.get_user(user_id, for_update=True)
            if user is None:
                raise ProfileUserNotFoundError()
            profile = await self.repository.get(user_id)
            previous = _read_state(profile) if profile else ProfileFields()
            state = ProfileFields.model_validate(
                previous.model_dump(include=set(ProfileFields.model_fields))
                | patch.model_dump(exclude_unset=True)
            )
            if "birth_time" in patch.model_fields_set:
                state.birth_time_known = patch.birth_time is not None
            birth_utc = _normalize_birth(state)
            if state.work_end <= state.work_start:
                raise ProfileValidationError(
                    "work_end", "WORK_WINDOW_INVALID", "Конец рабочего дня должен быть позже начала"
                )
            if (
                state.birth_date is not None
                and state.birth_date
                > to_utc(self.clock.now()).astimezone(parse_timezone(state.timezone)).date()
            ):
                raise ProfileValidationError(
                    "birth_date", "BIRTH_IN_FUTURE", "Дата рождения не может быть в будущем"
                )
            if (
                profile is not None
                and profile.onboarding_completed_at is not None
                and (state.birth_date is None or state.chronotype is None)
            ):
                raise ProfileIncompleteError()
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
            result = _read_state(profile)
            return ProfileUpdate(result, changed_fields, _document(user, result))
