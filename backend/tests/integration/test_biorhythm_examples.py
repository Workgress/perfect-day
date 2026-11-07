import copy
import json
from typing import Any

import pytest

from scripts.generate_biorhythm_vectors import FIXTURES_DIR
from tests.integration.test_profile_biorhythm_api import ProfileAPI
from tests.integration.test_profile_biorhythm_api import alembic_config as alembic_config
from tests.integration.test_profile_biorhythm_api import auth_api as auth_api
from tests.integration.test_profile_biorhythm_api import engine as engine
from tests.integration.test_profile_biorhythm_api import migrated_url as migrated_url
from tests.integration.test_profile_biorhythm_api import profile_api as profile_api

pytestmark = pytest.mark.docker
DATA = json.loads((FIXTURES_DIR / "biorhythm_api_examples.json").read_text(encoding="utf-8"))


def assert_response_matches_example(actual: Any, expected: Any, field: str = "") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key, value in expected.items():
            assert_response_matches_example(actual[key], value, key)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            assert_response_matches_example(actual_item, expected_item)
    elif field == "value":
        assert actual == pytest.approx(expected, rel=0, abs=1e-12)
    else:
        assert actual == expected


@pytest.mark.parametrize("name", DATA["examples"])
async def test_published_example_matches_live_api(profile_api: ProfileAPI, name: str) -> None:
    await profile_api.complete()
    example = copy.deepcopy(DATA["examples"][name])
    request = example["request"]
    expected = example["response"]
    response = await profile_api.api.client.request(
        request["method"],
        request["path"],
        params=request.get("query"),
        json=request.get("body"),
        headers={"Authorization": f"Bearer {profile_api.token}"},
    )
    assert response.status_code == expected["status"]
    assert response.headers["cache-control"] == expected["headers"]["Cache-Control"]
    if name in {"me", "patch_profile"}:
        expected["body"]["id"] = str(profile_api.user_id)
        expected["body"]["email"] = profile_api.api.email
    assert_response_matches_example(response.json(), expected["body"])
