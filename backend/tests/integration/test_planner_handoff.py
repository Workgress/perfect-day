import json
from datetime import datetime

import pytest

from app.core.time import FrozenClock
from app.modules.users.dependencies import get_clock
from scripts.generate_planner_cases import FIXTURES_DIR
from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url
from tests.integration.test_onboarding_api import counts, post
from tests.integration.test_profile_biorhythm_api import ProfileAPI
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

DATA = json.loads((FIXTURES_DIR / "planner_cases.json").read_text(encoding="utf-8"))
pytestmark = pytest.mark.docker


@pytest.mark.parametrize("case", DATA["http_preview_cases"], ids=lambda item: item["id"])
async def test_real_preview_matches_the_shared_frontend_fixture(
    profile_api: ProfileAPI, case: dict
) -> None:
    profile_api.api.app.dependency_overrides[get_clock] = lambda: FrozenClock(
        datetime.fromisoformat(case["now"])
    )
    assert (await profile_api.patch(case["profile_patch"])).status_code == 200
    response = await post(profile_api, "preview", case["request"])
    assert response.status_code == 200 and response.json() == case["expected"]
    assert await counts(profile_api) == [0, 0, 0]
