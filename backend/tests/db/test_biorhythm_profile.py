from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.biorhythm.engine import critical_info, snapshot
from app.modules.biorhythm.types import CriticalCrossing, CriticalKind, Cycle, Phase, Trend
from app.modules.users.schemas import ProfilePatch
from app.modules.users.service import ProfileService
from tests.db.factories import make_user

pytestmark = pytest.mark.docker


async def test_engine_uses_normalized_birth_from_profile(session: AsyncSession) -> None:
    user = await make_user(session)
    service = ProfileService(session, FrozenClock(datetime(2026, 11, 7, tzinfo=UTC)))
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {
                "birth_date": "2000-01-01",
                "birth_time": "12:00",
                "birth_tz": "Asia/Yekaterinburg",
            }
        ),
    )
    birth = update.profile.birth_at_utc
    assert birth == datetime(2000, 1, 1, 7, tzinfo=UTC)
    at = birth + timedelta(days=23 / 4)
    original = snapshot(birth, at)
    physical = original.cycles[Cycle.PHYSICAL]
    assert physical.value == 1.0 and physical.percent == 100.0
    assert physical.phase is Phase.PEAK and physical.trend is Trend.DOWN

    await service.update_profile(user.id, ProfilePatch(timezone="America/New_York"))
    profile = await service.get_profile(user.id)
    assert profile is not None and profile.birth_at_utc is not None
    assert snapshot(profile.birth_at_utc, at) == original

    corrected = await service.update_profile(user.id, ProfilePatch(birth_time=time(13)))
    assert corrected.profile.birth_at_utc is not None
    assert snapshot(corrected.profile.birth_at_utc, at).cycles[Cycle.PHYSICAL].value < 1.0


async def test_profile_timezone_changes_local_critical_day_not_crossing(
    session: AsyncSession,
) -> None:
    user = await make_user(session)
    service = ProfileService(session, FrozenClock(datetime(2026, 11, 7, tzinfo=UTC)))
    update = await service.update_profile(
        user.id,
        ProfilePatch.model_validate(
            {"birth_date": "2000-01-01", "birth_time": "12:00", "birth_tz": "Asia/Yekaterinburg"}
        ),
    )
    birth = update.profile.birth_at_utc
    assert birth is not None
    at = birth + timedelta(days=11.5)  # 19:00 UTC, midnight of next day in UTC+5
    original_day = at.date()
    before = critical_info(birth, original_day, ZoneInfo(update.profile.timezone))
    assert before.kind is CriticalKind.SINGLE
    assert before.crossings == (CriticalCrossing(Cycle.PHYSICAL, at),)

    await service.update_profile(user.id, ProfilePatch(timezone="Asia/Yekaterinburg"))
    profile = await service.get_profile(user.id)
    assert profile is not None and profile.birth_at_utc == birth
    tz = ZoneInfo(profile.timezone)
    assert critical_info(birth, original_day, tz).kind is CriticalKind.NONE
    shifted = critical_info(birth, at.astimezone(tz).date(), tz)
    assert shifted.crossings == before.crossings
