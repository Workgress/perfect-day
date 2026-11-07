import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.time import FrozenClock
from app.modules.users.models import Chronotype, ChronotypeSource, User, UserProfile
from app.modules.users.schemas import ProfilePatch
from app.modules.users.service import (
    ProfileService,
    ProfileUserNotFoundError,
    ProfileValidationError,
)
from tests.db.factories import make_user

pytestmark = pytest.mark.docker
NOW = datetime(2026, 11, 7, 10, tzinfo=UTC)
CLOCK = FrozenClock(NOW)
BIRTH = {
    "birth_date": "1995-03-14",
    "birth_time": "12:30",
    "birth_tz": "Asia/Yekaterinburg",
    "chronotype": "owl",
}


@pytest.fixture
async def committed_user_id(engine: AsyncEngine) -> AsyncIterator[UUID]:
    # Separate committed setup is needed to exercise multiple real transactions.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await make_user(session, f"{uuid4()}@example.ru")
        user_id = user.id
        await session.commit()
    try:
        yield user_id
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def test_empty_patch_creates_default_profile_and_reuses_it(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    assert await service.get_profile(user.id) is None
    first = await service.update_profile(user.id, ProfilePatch())
    second = await service.update_profile(user.id, ProfilePatch())
    assert first.profile == second.profile
    assert second.changed_fields == frozenset()
    assert first.profile.birth_at_utc is None
    assert first.profile.onboarding_completed_at is None
    assert first.profile.timezone == "UTC"
    count = await session.scalar(select(func.count()).select_from(UserProfile))
    assert count == 1


async def test_partial_patch_preserves_omitted_fields(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    before = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(BIRTH | {"display_name": "Алексей", "work_start": "09:00"}),
    )
    after = await service.update_profile(user.id, ProfilePatch(display_name="  Ирина  "))
    assert after.profile.display_name == "Ирина"
    assert after.changed_fields == frozenset({"display_name"})
    assert after.profile.birth_at_utc == before.profile.birth_at_utc
    assert after.profile.birth_time == time(12, 30)
    assert after.profile.chronotype is Chronotype.OWL
    assert after.profile.work_start == time(9)
    assert after.profile.timezone == "UTC"
    stored = await session.get(UserProfile, user.id)
    assert stored is not None and stored.display_name == "Ирина"


async def test_explicit_null_clears_optional_and_derived_fields(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(
        user.id, ProfilePatch.model_validate(BIRTH | {"display_name": "А"})
    )
    update = await service.update_profile(
        user.id, ProfilePatch(display_name=None, birth_date=None, chronotype=None)
    )
    assert update.profile.display_name is None
    assert update.profile.birth_date is None
    assert update.profile.birth_at_utc is None
    assert update.profile.chronotype is None
    assert update.profile.chronotype_source is None
    assert update.profile.birth_time == time(12, 30)


async def test_birth_timezone_defaults_after_merging_patch(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {"birth_date": "2000-01-01", "birth_time": "12:00", "timezone": "Europe/Moscow"}
        ),
    )
    assert update.profile.birth_tz == "Europe/Moscow"
    assert update.profile.birth_at_utc == datetime(2000, 1, 1, 9, tzinfo=UTC)


async def test_current_timezone_change_preserves_birth_instant(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    before = await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    after = await service.update_profile(user.id, ProfilePatch(timezone="America/New_York"))
    assert after.profile.birth_at_utc == before.profile.birth_at_utc
    assert after.profile.birth_tz == "Asia/Yekaterinburg"
    assert after.changed_fields == frozenset({"timezone"})


async def test_birth_timezone_correction_recalculates_instant(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    update = await service.update_profile(user.id, ProfilePatch(birth_tz="UTC"))
    assert update.profile.birth_at_utc == datetime(1995, 3, 14, 12, 30, tzinfo=UTC)
    assert update.changed_fields == frozenset({"birth_tz", "birth_at_utc"})


async def test_unknown_birth_time_is_noon_and_can_be_corrected(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate({"birth_date": "2000-02-29", "birth_time_known": False}),
    )
    assert update.profile.birth_time == time(12)
    assert update.profile.birth_at_utc == datetime(2000, 2, 29, 12, tzinfo=UTC)
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(user.id, ProfilePatch(birth_time_known=True))
    assert error.value.code == "BIRTH_TIME_REQUIRED"
    corrected = await service.update_profile(
        user.id, ProfilePatch.model_validate({"birth_time_known": True, "birth_time": "09:00"})
    )
    assert corrected.profile.birth_time == time(9)
    assert corrected.profile.birth_time_known is True


async def test_incomplete_profile_can_be_filled_in_separate_patches(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    first = await service.update_profile(user.id, ProfilePatch(birth_date=date(2000, 1, 1)))
    assert first.profile.birth_at_utc is None
    second = await service.update_profile(user.id, ProfilePatch(birth_time=time(8)))
    assert second.profile.birth_at_utc == datetime(2000, 1, 1, 8, tzinfo=UTC)
    assert second.profile.onboarding_completed_at is None


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"work_start": "19:00"}, "WORK_WINDOW_INVALID"),
        ({"sleep_time": "07:00"}, "SLEEP_WINDOW_INVALID"),
        ({"birth_date": "2026-11-08"}, "BIRTH_IN_FUTURE"),
        ({"birth_date": "2026-11-07", "birth_time": "11:00"}, "BIRTH_IN_FUTURE"),
        ({"birth_time_known": False, "birth_time": "13:00"}, "UNKNOWN_BIRTH_TIME"),
        (
            {"birth_date": "2026-03-29", "birth_time": "02:30", "birth_tz": "Europe/Berlin"},
            "BIRTH_TIME_NONEXISTENT",
        ),
        (
            {"birth_date": "2026-10-25", "birth_time": "02:30", "birth_tz": "Europe/Berlin"},
            "BIRTH_TIME_AMBIGUOUS",
        ),
    ],
)
async def test_invalid_update_is_atomic_and_session_remains_usable(
    session: AsyncSession, patch: dict[str, Any], code: str
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch(display_name="Исходное имя"))
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(
            user.id, ProfilePatch.model_validate(patch | {"display_name": "Не сохранять"})
        )
    assert error.value.code == code
    persisted = await service.get_profile(user.id)
    assert persisted is not None and persisted.display_name == "Исходное имя"
    valid = await service.update_profile(user.id, ProfilePatch(display_name="Сохранено"))
    assert valid.profile.display_name == "Сохранено"


@pytest.mark.parametrize("field", ["birth_date", "birth_time", "chronotype"])
async def test_completed_profile_cannot_lose_required_data(
    session: AsyncSession, field: str
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    before = await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.onboarding_completed_at = NOW
    await session.flush()
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(user.id, ProfilePatch.model_validate({field: None}))
    assert error.value.code == "ONBOARDING_DATA_REQUIRED"
    after = await service.get_profile(user.id)
    assert after is not None
    assert after.birth_at_utc == before.profile.birth_at_utc
    assert after.birth_date == before.profile.birth_date
    assert after.birth_time == before.profile.birth_time
    assert after.chronotype == before.profile.chronotype
    assert after.onboarding_completed_at == NOW


async def test_completed_profile_accepts_valid_partial_correction(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    profile = await session.get(UserProfile, user.id)
    assert profile is not None
    profile.onboarding_completed_at = NOW
    profile.chronotype_source = ChronotypeSource.QUIZ
    await session.flush()
    renamed = await service.update_profile(user.id, ProfilePatch(display_name="Алексей"))
    assert renamed.profile.chronotype_source is ChronotypeSource.QUIZ
    corrected = await service.update_profile(user.id, ProfilePatch(chronotype=Chronotype.LARK))
    assert corrected.profile.chronotype_source is ChronotypeSource.MANUAL
    assert corrected.profile.onboarding_completed_at == NOW


async def test_sleep_across_midnight_and_empty_week_are_valid(session: AsyncSession) -> None:
    user = await make_user(session)
    update = await ProfileService(session, CLOCK).update_profile(
        user.id, ProfilePatch(sleep_time=time(1), work_days=[])
    )
    assert update.profile.sleep_time == time(1)
    assert update.profile.work_days == []


async def test_profile_lookup_and_updates_are_scoped_to_user(session: AsyncSession) -> None:
    first = await make_user(session, "first@example.ru")
    second = await make_user(session, "second@example.ru")
    service = ProfileService(session, CLOCK)
    await service.update_profile(first.id, ProfilePatch(display_name="Первый"))
    assert await service.get_profile(second.id) is None
    await service.update_profile(second.id, ProfilePatch(display_name="Второй"))
    profile = await service.get_profile(first.id)
    assert profile is not None and profile.display_name == "Первый"


async def test_missing_user_cannot_create_profile(session: AsyncSession) -> None:
    with pytest.raises(ProfileUserNotFoundError):
        await ProfileService(session, CLOCK).update_profile(uuid4(), ProfilePatch())
    assert await session.scalar(select(func.count()).select_from(UserProfile)) == 0


@pytest.mark.parametrize("state", ["inactive", "deleted"])
async def test_inactive_or_deleted_user_cannot_access_profile(
    session: AsyncSession, state: str
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch())
    if state == "inactive":
        user.is_active = False
    else:
        user.deleted_at = NOW
    await session.flush()
    assert await service.get_profile(user.id) is None
    with pytest.raises(ProfileUserNotFoundError):
        await service.update_profile(user.id, ProfilePatch(display_name="Изменено"))


async def test_invalid_initial_patch_does_not_create_profile(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    with pytest.raises(ProfileValidationError):
        await service.update_profile(user.id, ProfilePatch(work_start=time(19)))
    assert await service.get_profile(user.id) is None
    update = await service.update_profile(user.id, ProfilePatch(display_name="После ошибки"))
    assert update.profile.display_name == "После ошибки"


async def test_birth_date_uses_birth_timezone_not_server_date(session: AsyncSession) -> None:
    user = await make_user(session)
    clock = FrozenClock(datetime(2026, 11, 7, 23, 30, tzinfo=UTC))
    service = ProfileService(session, clock)
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {"birth_date": "2026-11-08", "birth_time": "13:00", "birth_tz": "Pacific/Kiritimati"}
        ),
    )
    assert update.profile.birth_at_utc == datetime(2026, 11, 7, 23, tzinfo=UTC)
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(user.id, ProfilePatch(birth_time=time(14)))
    assert error.value.code == "BIRTH_IN_FUTURE"


async def test_birth_timezone_null_explicitly_selects_current_timezone(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    update = await service.update_profile(user.id, ProfilePatch(birth_tz=None))
    assert update.profile.birth_tz == "UTC"
    assert update.profile.birth_at_utc == datetime(1995, 3, 14, 12, 30, tzinfo=UTC)


async def test_service_does_not_commit_outer_transaction(
    engine: AsyncEngine, committed_user_id: UUID
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await ProfileService(session, CLOCK).update_profile(
            committed_user_id, ProfilePatch(display_name="Отменить")
        )
        await session.rollback()
    async with factory() as observer:
        assert await ProfileService(observer, CLOCK).get_profile(committed_user_id) is None


async def test_concurrent_initial_patches_preserve_both_changes(
    engine: AsyncEngine, committed_user_id: UUID
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ready = asyncio.Barrier(2)

    async def update(patch: ProfilePatch) -> None:
        async with factory() as session:
            service = ProfileService(session, CLOCK)
            assert await service.get_profile(committed_user_id) is None
            await ready.wait()
            await service.update_profile(committed_user_id, patch)
            await session.commit()

    async with asyncio.timeout(10):
        await asyncio.gather(
            update(ProfilePatch(display_name="Параллельное обновление")),
            update(ProfilePatch(timezone="Europe/Moscow")),
        )
    async with factory() as observer:
        profile = await ProfileService(observer, CLOCK).get_profile(committed_user_id)
        assert profile is not None
        assert profile.display_name == "Параллельное обновление"
        assert profile.timezone == "Europe/Moscow"
        count = await observer.scalar(
            select(func.count())
            .select_from(UserProfile)
            .where(UserProfile.user_id == committed_user_id)
        )
        assert count == 1
