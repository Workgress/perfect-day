from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.biorhythm.engine import snapshot
from app.modules.biorhythm.types import Cycle, Phase, Trend
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
