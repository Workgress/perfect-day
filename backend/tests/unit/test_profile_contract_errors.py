import json

import pytest
from starlette.requests import Request

from app.core.errors import AppError, app_error_handler
from app.modules.biorhythm.service import BiorhythmValidationError, OnboardingRequiredError
from app.modules.users.service import (
    ProfileIncompleteError,
    ProfileUserNotFoundError,
    ProfileValidationError,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProfileIncompleteError(), 409, "PROFILE_INCOMPLETE"),
        (OnboardingRequiredError(), 409, "ONBOARDING_REQUIRED"),
        (ProfileUserNotFoundError(), 401, "AUTHENTICATION_REQUIRED"),
        (
            ProfileValidationError("work_end", "WORK_WINDOW_INVALID", "Некорректное окно"),
            422,
            "VALIDATION_ERROR",
        ),
        (BiorhythmValidationError("from", "BEFORE_BIRTH", "До рождения"), 422, "VALIDATION_ERROR"),
    ],
)
async def test_domain_errors_use_existing_main_handler(
    error: AppError, status: int, code: str
) -> None:
    response = await app_error_handler(Request({"type": "http"}), error)
    payload = json.loads(response.body)
    assert response.status_code == status and payload["error"]["code"] == code
    assert isinstance(payload["error"]["details"], dict)
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"
    if status == 422:
        field = payload["error"]["details"]["fields"][0]["field"]
        assert field.startswith(("query.", "body."))
