from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.users.schemas import ProfileFields, ProfilePatch, ProfileResponse


def test_patch_distinguishes_omitted_and_explicit_null() -> None:
    assert ProfilePatch().model_dump(exclude_unset=True) == {}
    assert ProfilePatch(display_name=None).model_dump(exclude_unset=True) == {"display_name": None}


def test_defaults_match_database() -> None:
    profile = ProfileFields()
    assert profile.timezone == "UTC"
    assert profile.birth_time_known is True
    assert profile.wake_time == time(7) and profile.sleep_time == time(23)
    assert profile.work_start == time(8) and profile.work_end == time(18)
    assert profile.work_days == [1, 2, 3, 4, 5]
    assert profile.lunch_start == time(12) and profile.lunch_duration_min == 60


def test_profile_days_are_not_shared_between_instances() -> None:
    first = ProfilePatch()
    first.work_days.append(6)
    assert ProfilePatch().work_days == [1, 2, 3, 4, 5]


def test_name_is_trimmed_and_local_values_are_parsed() -> None:
    patch = ProfilePatch.model_validate(
        {"display_name": "  Алексей  ", "birth_date": "1995-03-14", "birth_time": "12:30:05"}
    )
    assert patch.display_name == "Алексей"
    assert patch.birth_date == date(1995, 3, 14)
    assert patch.birth_time == time(12, 30, 5)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", "  "),
        ("display_name", "x" * 101),
        ("birth_date", "1899-12-31"),
        ("birth_date", "2000-02-30"),
        ("birth_date", "20000101"),
        ("birth_date", 946684800),
        ("birth_date", datetime(2000, 1, 1)),
        ("birth_time", "12:00:00.001"),
        ("birth_time", "12:00+05:00"),
        ("birth_time", "24:00"),
        ("birth_time", "1:00"),
        ("birth_time", 3600),
        ("birth_time", time(12, tzinfo=UTC)),
        ("birth_time", time(12, microsecond=1)),
        ("birth_time_known", 1),
        ("birth_time_known", "false"),
        ("timezone", "Not/AZone"),
        ("birth_tz", "../UTC"),
        ("chronotype", "night"),
        ("work_days", [1, 1]),
        ("work_days", [0, 1]),
        ("work_days", [8]),
        ("work_days", [True]),
        ("work_days", ["1"]),
        ("lunch_duration_min", -1),
        ("lunch_duration_min", 181),
        ("lunch_duration_min", 1.5),
        ("lunch_duration_min", True),
    ],
)
def test_invalid_patch_fields(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        ProfilePatch.model_validate({field: value})


@pytest.mark.parametrize(
    "field",
    [
        "timezone",
        "birth_time_known",
        "wake_time",
        "sleep_time",
        "lunch_start",
        "lunch_duration_min",
        "work_start",
        "work_end",
        "work_days",
    ],
)
def test_required_settings_cannot_be_null(field: str) -> None:
    with pytest.raises(ValidationError):
        ProfilePatch.model_validate({field: None})


@pytest.mark.parametrize(
    "field",
    ["user_id", "birth_at_utc", "chronotype_source", "onboarding_completed_at", "updated_at"],
)
def test_readonly_fields_cannot_be_patched(field: str) -> None:
    with pytest.raises(ValidationError) as error:
        ProfilePatch.model_validate({field: None})
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_empty_work_week_is_valid() -> None:
    assert ProfilePatch(work_days=[]).work_days == []


def test_response_serializes_utc_timestamps_and_excludes_private_data() -> None:
    profile = ProfileResponse.model_validate(
        {
            "birth_at_utc": "1995-03-14T12:00:00+05:00",
            "chronotype_source": None,
            "onboarding_completed_at": None,
            "updated_at": "2026-11-07T15:00:00+05:00",
        }
    )
    data = profile.model_dump(mode="json")
    assert data["birth_at_utc"] == "1995-03-14T07:00:00Z"
    assert data["updated_at"] == "2026-11-07T10:00:00Z"
    assert not {"user_id", "password_hash"} & data.keys()
