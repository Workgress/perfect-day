import re
from datetime import date, datetime, time
from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)

from app.core.time import parse_timezone, to_utc
from app.modules.users.models import Chronotype, ChronotypeSource


def _local_time(value: Any) -> time:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", value):
            raise ValueError("Укажите время в формате HH:MM или HH:MM:SS")
        value = time.fromisoformat(value)
    if not isinstance(value, time) or value.tzinfo is not None or value.microsecond:
        raise ValueError("Время должно быть без пояса, с точностью до секунды")
    return value


LocalTime = Annotated[time, BeforeValidator(_local_time)]
Weekday = Annotated[StrictInt, Field(ge=1, le=7)]


def _birth_date(value: Any) -> date:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Укажите дату в формате YYYY-MM-DD")
        value = date.fromisoformat(value)
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Укажите дату без времени")
    return value


BirthDate = Annotated[date, BeforeValidator(_birth_date), Field(ge=date(1900, 1, 1))]


class ProfileFields(BaseModel):
    """Editable data and defaults shared by PATCH and merged-state validation."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    display_name: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    birth_date: BirthDate | None = None
    birth_time: LocalTime | None = None
    birth_time_known: StrictBool = True
    birth_tz: str | None = None
    chronotype: Chronotype | None = None
    timezone: str = "UTC"
    wake_time: LocalTime = time(7)
    sleep_time: LocalTime = time(23)
    lunch_start: LocalTime = time(12)
    lunch_duration_min: Annotated[StrictInt, Field(ge=0, le=180)] = 60
    work_start: LocalTime = time(8)
    work_end: LocalTime = time(18)
    work_days: list[Weekday] = Field(default_factory=lambda: [1, 2, 3, 4, 5])

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("timezone", "birth_tz")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            parse_timezone(value)
        return value

    @field_validator("work_days")
    @classmethod
    def unique_work_days(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("Рабочие дни не должны повторяться")
        return value


class ProfilePatch(ProfileFields):
    """Only model_fields_set / exclude_unset define the actual patch."""


class ProfileResponse(ProfileFields):
    birth_at_utc: AwareDatetime | None
    chronotype_source: ChronotypeSource | None
    onboarding_completed_at: AwareDatetime | None
    updated_at: AwareDatetime

    @field_validator("birth_at_utc", "onboarding_completed_at", "updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return to_utc(value) if value is not None else None
