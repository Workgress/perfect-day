import re
from datetime import date, datetime, time
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from starlette.datastructures import QueryParams

from app.core.time import to_utc
from app.modules.tasks.models import TaskPriority, TaskStatus, TaskType


def _trim_title(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _local_date(value: Any) -> date:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raise ValueError("Укажите дату без времени в формате YYYY-MM-DD")


def _timestamp(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ]", value):
        return value
    raise ValueError("Укажите дату и время ISO 8601 с явным UTC-смещением")


def _query_integer(value: Any) -> Any:
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]+", value):
            raise ValueError("Укажите целое число")
        return int(value)
    return value


TaskTitle = Annotated[str, BeforeValidator(_trim_title), Field(min_length=1, max_length=200)]
TaskDate = Annotated[date, BeforeValidator(_local_date)]
TaskTimestamp = Annotated[AwareDatetime, BeforeValidator(_timestamp), AfterValidator(to_utc)]
TaskDuration = Annotated[StrictInt, Field(ge=5, le=480)]
TaskVersion = Annotated[StrictInt, Field(ge=1)]
QueryInteger = Annotated[StrictInt, BeforeValidator(_query_integer)]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TaskTitle
    description: str | None = None
    type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    duration_min: TaskDuration
    planned_date: TaskDate
    deadline: TaskTimestamp | None = None


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: TaskVersion
    title: TaskTitle | SkipJsonSchema[None] = None
    description: str | None = None
    type: TaskType | SkipJsonSchema[None] = None
    priority: TaskPriority | SkipJsonSchema[None] = None
    duration_min: TaskDuration | SkipJsonSchema[None] = None
    planned_date: TaskDate | SkipJsonSchema[None] = None
    deadline: TaskTimestamp | None = None

    @field_validator("title", "type", "priority", "duration_min", "planned_date", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Это поле нельзя очистить")
        return value

    @model_validator(mode="after")
    def require_changes(self) -> "TaskPatch":
        if self.model_fields_set == {"version"}:
            raise ValueError("Передайте хотя бы одно изменяемое поле")
        return self


class TaskStatusCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: TaskVersion


class TaskQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_duplicate_parameters(cls, value: Any) -> Any:
        if isinstance(value, QueryParams):
            if len(value.multi_items()) != len(value):
                raise ValueError("Параметры запроса не должны повторяться")
            return dict(value)
        return value


class TaskListQuery(TaskQuery):
    date: TaskDate | None = None
    from_date: TaskDate | None = Field(default=None, alias="from")
    to_date: TaskDate | None = Field(default=None, alias="to")
    status: TaskStatus | None = None
    type: TaskType | None = None
    limit: Annotated[QueryInteger, Field(ge=1, le=100)] = 50
    offset: Annotated[QueryInteger, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_date_filters(self) -> "TaskListQuery":
        if self.date is not None and (self.from_date is not None or self.to_date is not None):
            raise ValueError("Параметр date нельзя сочетать с from или to")
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("Дата from не может быть позже to")
        return self


class TaskDeleteQuery(TaskQuery):
    version: Annotated[QueryInteger, Field(ge=1)]


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    title: TaskTitle
    description: str | None
    type: TaskType
    priority: TaskPriority
    duration_min: TaskDuration
    planned_date: TaskDate
    deadline: TaskTimestamp | None
    status: TaskStatus
    completed_at: TaskTimestamp | None
    version: TaskVersion
    created_at: TaskTimestamp
    updated_at: TaskTimestamp
    preferred_start: time | None
    is_pinned: StrictBool
    pinned_start: TaskTimestamp | None


class TaskList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskResponse]
    total: Annotated[StrictInt, Field(ge=0)]
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    offset: Annotated[StrictInt, Field(ge=0)]
