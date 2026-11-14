"""Approved onboarding contract, sections 7-8; task CRUD has separate ownership."""

import re
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

from app.modules.planner.documentation import REQUEST_EXAMPLE
from app.modules.tasks.models import TaskType
from app.modules.users.schemas import MinuteTime


def _calendar_date(value: Any) -> date:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Укажите дату YYYY-MM-DD")
        value = date.fromisoformat(value)
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("Укажите календарную дату")
    return value


class FirstTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr
    type: TaskType
    duration_min: Annotated[StrictInt, Field(ge=5, le=480)]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not 1 <= len(value.strip()) <= 200:
            raise ValueError("После удаления пробелов название должно содержать 1-200 символов")
        # Keep the parsed original for idempotency; trim only when persisting a task.
        return value


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [REQUEST_EXAMPLE]})

    planned_date: Annotated[date, BeforeValidator(_calendar_date)]
    tasks: Annotated[list[FirstTask], Field(min_length=1, max_length=100)]


class PreviewSlot(BaseModel):
    task_index: int
    start_time: MinuteTime
    end_time: MinuteTime
    explanation: Annotated[str, Field(min_length=1)]


class PlanPreview(BaseModel):
    planned_date: date
    timezone: str
    slots: list[PreviewSlot]
    unscheduled_task_indexes: list[int]
