import json
from math import ceil
from time import perf_counter_ns

import pytest

from tests.integration.test_auth import alembic_config as alembic_config
from tests.integration.test_auth import auth_api as auth_api
from tests.integration.test_auth import engine as engine
from tests.integration.test_auth import migrated_url as migrated_url
from tests.integration.test_onboarding_api import counts, post, prepare
from tests.integration.test_profile_biorhythm_api import ProfileAPI
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

pytestmark = [pytest.mark.docker, pytest.mark.performance]


async def test_preview_fifty_tasks_p95_under_300ms(
    profile_api: ProfileAPI, pytestconfig: pytest.Config
) -> None:
    if pytestconfig.getoption("cov_source", default=[]):
        pytest.skip("Timing is checked separately without coverage instrumentation")
    await prepare(profile_api)
    kinds = ("intellectual", "physical", "creative", "routine")
    body = {
        "planned_date": "2026-11-08",
        "tasks": [
            {"title": f"Задача {i}", "type": kinds[i % 4], "duration_min": (5, 17)[i % 2]}
            for i in range(50)
        ],
    }
    durations = []
    for index in range(12):
        start = perf_counter_ns()
        response = await post(profile_api, "preview", body)
        elapsed = (perf_counter_ns() - start) / 1_000_000
        assert response.status_code == 200
        result = response.json()
        assert len(result["slots"]) + len(result["unscheduled_task_indexes"]) == 50
        if index >= 2:
            durations.append(elapsed)
    p95 = sorted(durations)[ceil(0.95 * len(durations)) - 1]
    print(json.dumps({"http_preview_50_samples": len(durations), "p95_ms": round(p95, 3)}))
    assert p95 < 300
    assert await counts(profile_api) == [0, 0, 0]
