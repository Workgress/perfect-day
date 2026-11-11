import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.time import FrozenClock
from app.modules.users.models import Chronotype, ChronotypeSource, User, UserProfile
from app.modules.users.schemas import ProfilePatch
from app.modules.users.service import (
    ProfileIncompleteError,
    ProfileService,
    ProfileUserNotFoundError,
    ProfileValidationError,
)
from tests.db.factories import make_user

pytestmark = pytest.mark.docker
NOW = datetime(2026, 11, 7, 10, tzinfo=UTC)
CLOCK = FrozenClock(NOW)
BIRTH = {"birth_date": "1995-03-14", "birth_time": "12:30:00", "chronotype": "owl"}


@pytest.fixture
async def committed_user_id(engine: AsyncEngine) -> AsyncIterator[UUID]:
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


async def test_new_user_document_and_empty_patch_follow_contract(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    fresh = await service.get_document(user.id)
    assert fresh.profile is None and fresh.onboarding.next_step == "birth_date"
    update = await service.update_profile(user.id, ProfilePatch())
    assert update.document.profile is not None
    assert update.document.profile.birth_time is None
    assert update.document.profile.work_start == time(8)
    second = await service.update_profile(user.id, ProfilePatch())
    assert second.changed_fields == frozenset()
    assert second.document == await service.get_document(user.id)
    data = second.document.model_dump(mode="json")
    assert set(data) == {"id", "email", "display_name", "profile", "onboarding"}
    assert set(data["profile"]) == {
        "birth_date",
        "birth_time",
        "timezone",
        "chronotype",
        "work_start",
        "work_end",
        "sleep_time",
    }


async def test_partial_patch_preserves_omitted_fields_and_name(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(
        user.id, ProfilePatch.model_validate(BIRTH | {"work_start": "09:00:00"})
    )
    stored = await session.get(UserProfile, user.id)
    assert stored is not None
    stored.display_name = "Алексей"
    await session.flush()
    update = await service.update_profile(user.id, ProfilePatch(sleep_time=time(1)))
    assert update.changed_fields == frozenset({"sleep_time"})
    assert update.profile.birth_time == time(12, 30)
    assert update.profile.work_start == time(9)
    assert update.profile.chronotype is Chronotype.OWL
    assert update.document.display_name == "Алексей"


async def test_onboarding_progress_tracks_saved_data_not_client_flags(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    first = await service.update_profile(user.id, ProfilePatch(birth_date=date(2000, 1, 1)))
    assert first.document.onboarding.next_step == "chronotype"
    assert first.profile.birth_at_utc == datetime(2000, 1, 1, 12, tzinfo=UTC)
    second = await service.update_profile(user.id, ProfilePatch(chronotype=Chronotype.DOVE))
    assert second.document.onboarding.next_step == "first_tasks"
    assert second.document.onboarding.completed_at is None


async def test_unknown_time_stays_null_publicly_and_uses_noon_internally(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {
                "birth_date": "2000-02-29",
                "birth_time": None,
                "timezone": "Asia/Yekaterinburg",
            }
        ),
    )
    assert update.profile.birth_at_utc == datetime(2000, 2, 29, 12, tzinfo=UTC)
    assert update.profile.birth_time == time(12) and not update.profile.birth_time_known
    assert update.document.profile is not None and update.document.profile.birth_time is None
    known = await service.update_profile(user.id, ProfilePatch(birth_time=time(9)))
    assert known.profile.birth_time_known and known.profile.birth_at_utc.hour == 9
    unknown = await service.update_profile(user.id, ProfilePatch(birth_time=None))
    assert unknown.profile.birth_at_utc.hour == 12 and not unknown.profile.birth_time_known


async def test_timezone_never_changes_computational_birth_scale(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    first = await service.update_profile(
        user.id, ProfilePatch.model_validate(BIRTH | {"timezone": "Europe/Berlin"})
    )
    assert first.profile.birth_tz == "UTC"
    assert first.profile.birth_at_utc == datetime(1995, 3, 14, 12, 30, tzinfo=UTC)
    second = await service.update_profile(user.id, ProfilePatch(timezone="America/New_York"))
    assert second.profile.birth_at_utc == first.profile.birth_at_utc
    assert second.changed_fields == frozenset({"timezone"})


async def test_current_local_birth_date_is_allowed_even_if_virtual_utc_time_is_future(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, FrozenClock(datetime(2026, 11, 7, 23, 30, tzinfo=UTC)))
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {
                "birth_date": "2026-11-08",
                "birth_time": "13:00:00",
                "timezone": "Pacific/Kiritimati",
            }
        ),
    )
    assert update.profile.birth_at_utc == datetime(2026, 11, 8, 13, tzinfo=UTC)
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(user.id, ProfilePatch(birth_date=date(2026, 11, 9)))
    assert error.value.body.code == "VALIDATION_ERROR"


async def test_bad_patch_is_atomic_and_uses_shared_errors(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    with pytest.raises(ProfileValidationError) as error:
        await service.update_profile(
            user.id, ProfilePatch(work_start=time(19), chronotype=Chronotype.LARK)
        )
    assert error.value.status_code == 422
    assert error.value.body.details["fields"][0]["field"] == "body.work_end"
    stored = await service.get_profile(user.id)
    assert stored is not None and stored.chronotype is Chronotype.OWL
    valid = await service.update_profile(user.id, ProfilePatch(work_start=time(9)))
    assert valid.profile.work_start == time(9)


@pytest.mark.parametrize("field", ["birth_date", "chronotype"])
async def test_completed_profile_rejects_required_null_with_409(
    session: AsyncSession, field: str
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    stored = await session.get(UserProfile, user.id)
    assert stored is not None
    stored.onboarding_completed_at = NOW
    await session.flush()
    with pytest.raises(ProfileIncompleteError) as error:
        await service.update_profile(user.id, ProfilePatch.model_validate({field: None}))
    assert error.value.status_code == 409 and error.value.body.code == "PROFILE_INCOMPLETE"
    document = await service.get_document(user.id)
    assert document.onboarding.completed_at == NOW and document.onboarding.next_step is None


async def test_completed_profile_can_clear_optional_time_and_keep_completion(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    stored = await session.get(UserProfile, user.id)
    assert stored is not None
    stored.onboarding_completed_at = NOW
    stored.chronotype_source = ChronotypeSource.QUIZ
    await session.flush()
    update = await service.update_profile(user.id, ProfilePatch(birth_time=None))
    assert update.document.profile.birth_time is None
    assert update.document.onboarding.completed_at == NOW
    assert update.profile.chronotype_source is ChronotypeSource.QUIZ
    corrected = await service.update_profile(user.id, ProfilePatch(chronotype=Chronotype.LARK))
    assert corrected.profile.chronotype_source is ChronotypeSource.MANUAL


async def test_legacy_birth_zone_is_canonicalized_without_read_side_effects(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    stored = UserProfile(
        user_id=user.id,
        birth_date=date(2000, 1, 1),
        birth_time=time(12),
        birth_time_known=True,
        birth_tz="Asia/Yekaterinburg",
        birth_at_utc=datetime(2000, 1, 1, 7, tzinfo=UTC),
    )
    session.add(stored)
    await session.flush()
    service = ProfileService(session, CLOCK)
    state = await service.get_profile(user.id)
    assert state.birth_at_utc == datetime(2000, 1, 1, 12, tzinfo=UTC)
    await session.refresh(stored)
    assert stored.birth_at_utc.hour == 7
    update = await service.update_profile(user.id, ProfilePatch())
    assert {"birth_at_utc", "birth_tz"} <= update.changed_fields
    assert stored.birth_tz == "UTC" and stored.birth_at_utc.hour == 12


async def test_optional_null_clears_unfinished_profile_and_progress(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, CLOCK)
    await service.update_profile(user.id, ProfilePatch.model_validate(BIRTH))
    update = await service.update_profile(user.id, ProfilePatch(birth_date=None, chronotype=None))
    assert update.profile.birth_at_utc is None and update.profile.chronotype_source is None
    assert update.document.onboarding.next_step == "birth_date"


async def test_legacy_seconds_are_normalized_for_v1_without_changing_main_models(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    stored = UserProfile(
        user_id=user.id,
        birth_date=date(2000, 1, 1),
        birth_time=time(12, 30, 5),
        birth_time_known=True,
        work_start=time(9, 0, 5),
        sleep_time=time(23, 0, 20),
    )
    session.add(stored)
    await session.flush()
    service = ProfileService(session, CLOCK)
    document = await service.get_document(user.id)
    assert document.profile.birth_time == time(12, 30)
    assert document.profile.work_start == time(9)
    await session.refresh(stored)
    assert stored.birth_time.second == 5
    update = await service.update_profile(user.id, ProfilePatch())
    assert update.profile.birth_at_utc == datetime(2000, 1, 1, 12, 30, tzinfo=UTC)
    assert stored.birth_time.second == 0 and stored.sleep_time.second == 0


async def test_missing_and_inactive_users_are_not_accessible(session: AsyncSession) -> None:
    service = ProfileService(session, CLOCK)
    with pytest.raises(ProfileUserNotFoundError):
        await service.get_document(uuid4())
    user = await make_user(session)
    user.is_active = False
    await session.flush()
    with pytest.raises(ProfileUserNotFoundError):
        await service.update_profile(user.id, ProfilePatch())


async def test_service_does_not_commit_outer_transaction(
    engine: AsyncEngine, committed_user_id: UUID
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await ProfileService(session, CLOCK).update_profile(
            committed_user_id, ProfilePatch(timezone="Europe/Moscow")
        )
        await session.rollback()
    async with factory() as session:
        assert await session.get(UserProfile, committed_user_id) is None


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
            update(ProfilePatch(work_start=time(9))), update(ProfilePatch(timezone="Europe/Moscow"))
        )
    async with factory() as session:
        profile = await session.scalar(
            select(UserProfile).where(UserProfile.user_id == committed_user_id)
        )
        assert (
            profile is not None
            and profile.work_start == time(9)
            and profile.timezone == "Europe/Moscow"
        )
