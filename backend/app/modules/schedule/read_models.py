from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.core.time import parse_timezone, to_utc
from app.modules.planner.contracts import SlotKind

ReadTimestamp = Annotated[AwareDatetime, AfterValidator(to_utc)]


class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScheduleReadSlot(ReadModel):
    id: UUID
    kind: SlotKind
    task_id: UUID | None
    start_at: ReadTimestamp
    end_at: ReadTimestamp
    is_pinned: bool
    reason_codes: tuple[str, ...]
    explanation: str | None

    @model_validator(mode="after")
    def validate_interval_and_task(self) -> "ScheduleReadSlot":
        if self.end_at <= self.start_at:
            raise ValueError("Slot end must be after start")
        if (self.kind == "task") != (self.task_id is not None):
            raise ValueError("Only task slots must reference a task")
        return self


class ScheduleReadUnscheduled(ReadModel):
    task_id: UUID
    reason_codes: tuple[str, ...]


class ScheduleReadMetrics(ReadModel):
    requested_min: int
    planned_min: int
    capacity_min: int
    high_intensity_min: int
    critical_level: int
    load_factor: float
    moved_min: int


class ScheduleReadWarning(ReadModel):
    code: str
    message: str
    level: Literal["info", "warning", "critical"]
    task_id: UUID | None
    target_date: date | None


class ScheduleReadMove(ReadModel):
    task_id: UUID
    from_date: date
    to_date: date
    reason_code: str


class ScheduleReadResult(ReadModel):
    id: UUID
    planned_date: date
    timezone: str
    version: Annotated[int, Field(ge=1)]
    algorithm_version: Annotated[str, Field(min_length=1)]
    generated_at: ReadTimestamp
    slots: tuple[ScheduleReadSlot, ...]
    unscheduled: tuple[ScheduleReadUnscheduled, ...]
    metrics: ScheduleReadMetrics
    warnings: tuple[ScheduleReadWarning, ...]
    moves: tuple[ScheduleReadMove, ...]

    @model_validator(mode="after")
    def validate_timezone(self) -> "ScheduleReadResult":
        parse_timezone(self.timezone)
        return self
