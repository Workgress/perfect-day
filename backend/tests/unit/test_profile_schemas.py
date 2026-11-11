from datetime import UTC, datetime, time
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.users.schemas import ProfileFields, ProfilePatch, ProfileState


def test_patch_distinguishes_omitted_and_explicit_null() -> None:
    assert ProfilePatch().model_dump(exclude_unset=True) == {}
    assert ProfilePatch(birth_time=None).model_dump(exclude_unset=True) == {"birth_time": None}


def test_only_contract_fields_are_publicly_editable() -> None:
    assert set(ProfilePatch.model_fields) == {
        "birth_date",
        "birth_time",
        "timezone",
        "chronotype",
        "work_start",
        "work_end",
        "sleep_time",
    }


def test_internal_defaults_do_not_claim_known_birth_time() -> None:
    state = ProfileFields()
    assert state.birth_time_known is False and state.birth_time == time(12)
    assert state.birth_tz == "UTC" and state.timezone == "UTC"
    assert state.work_start == time(8) and state.work_end == time(18)
    assert state.sleep_time == time(23)


def test_public_times_have_minute_precision() -> None:
    patch = ProfilePatch.model_validate({"birth_date": "1995-03-14", "birth_time": "12:30:00"})
    assert patch.birth_time == time(12, 30)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("birth_date", "1899-12-31"),
        ("birth_date", "2000-02-30"),
        ("birth_date", "20000101"),
        ("birth_date", 946684800),
        ("birth_date", datetime(2000, 1, 1)),
        ("birth_time", "12:00"),
        ("birth_time", "12:00:05"),
        ("birth_time", "12:00:00.001"),
        ("birth_time", "12:00:00+05:00"),
        ("birth_time", "24:00:00"),
        ("birth_time", 3600),
        ("birth_time", time(12, tzinfo=UTC)),
        ("birth_time", time(12, second=1)),
        ("timezone", "Not/AZone"),
        ("chronotype", "night"),
        ("work_end", "18:00:01"),
        ("sleep_time", "01:00"),
    ],
)
def test_invalid_patch_fields(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        ProfilePatch.model_validate({field: value})


@pytest.mark.parametrize("field", ["timezone", "work_start", "work_end", "sleep_time"])
def test_required_settings_cannot_be_null(field: str) -> None:
    with pytest.raises(ValidationError):
        ProfilePatch.model_validate({field: None})


@pytest.mark.parametrize(
    "field",
    [
        "display_name",
        "birth_tz",
        "birth_timezone",
        "birth_time_known",
        "user_id",
        "birth_at_utc",
        "chronotype_source",
        "onboarding_completed_at",
        "updated_at",
        "onboarding",
        "completed_at",
        "work_days",
        "wake_time",
        "lunch_start",
        "lunch_duration_min",
    ],
)
def test_private_or_uncontracted_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError) as error:
        ProfilePatch.model_validate({field: None})
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_internal_state_retains_utc_timestamps_for_calculations() -> None:
    state = ProfileState.model_validate(
        {
            "birth_at_utc": "1995-03-14T12:00:00+05:00",
            "chronotype_source": None,
            "onboarding_completed_at": None,
            "updated_at": "2026-11-07T15:00:00+05:00",
        }
    )
    assert state.birth_at_utc == datetime(1995, 3, 14, 7, tzinfo=UTC)
    assert state.updated_at == datetime(2026, 11, 7, 10, tzinfo=UTC)
