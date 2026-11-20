from typing import Annotated
from uuid import UUID

from pydantic import Field, StrictBool, StringConstraints, model_validator

from app.modules.planner.contracts import PlacementChangeKind, Preservation
from app.modules.schedule.read_models import ReadModel, ScheduleReadResult
from app.modules.tasks.schemas import TaskDate, TaskTimestamp, TaskVersion

ExplanationText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]


class ScheduleReplanRequest(ReadModel):
    planned_date: TaskDate
    allow_date_change: StrictBool = False


class PlacementCheckRequest(ReadModel):
    task_id: UUID
    version: TaskVersion
    planned_date: TaskDate
    start_at: TaskTimestamp
    end_at: TaskTimestamp

    @model_validator(mode="after")
    def validate_interval(self) -> "PlacementCheckRequest":
        if self.end_at <= self.start_at:
            raise ValueError("Конец интервала должен быть позже начала")
        return self


class PlacementRefusal(ReadModel):
    code: ReasonCode
    message: ExplanationText
    conflicting_task_id: UUID | None = None


class PlacementCheckResponse(ReadModel):
    task_id: UUID
    version: TaskVersion
    planned_date: TaskDate
    start_at: TaskTimestamp
    end_at: TaskTimestamp
    allowed: StrictBool
    reasons: tuple[PlacementRefusal, ...]

    @model_validator(mode="after")
    def validate_result(self) -> "PlacementCheckResponse":
        if self.end_at <= self.start_at:
            raise ValueError("Конец интервала должен быть позже начала")
        if self.allowed != (not self.reasons):
            raise ValueError("Отказ требует причины; разрешение не должно содержать причин отказа")
        return self


class TaskMoveRecommendation(ReadModel):
    task_id: UUID
    from_date: TaskDate
    to_date: TaskDate
    reason_code: ReasonCode
    explanation: ExplanationText

    @model_validator(mode="after")
    def validate_dates(self) -> "TaskMoveRecommendation":
        if self.to_date <= self.from_date:
            raise ValueError("Предлагаемая дата должна быть позже исходной")
        return self


class UnscheduledTaskExplanation(ReadModel):
    task_id: UUID
    planned_date: TaskDate
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(min_length=1)]
    explanation: ExplanationText


class TaskPlacementExplanation(ReadModel):
    task_id: UUID
    planned_date: TaskDate
    start_at: TaskTimestamp
    end_at: TaskTimestamp
    preservation: Preservation | None
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(min_length=1)]
    explanation: ExplanationText

    @model_validator(mode="after")
    def validate_interval(self) -> "TaskPlacementExplanation":
        if self.end_at <= self.start_at:
            raise ValueError("Конец интервала должен быть позже начала")
        return self


class ScheduleExplanations(ReadModel):
    unscheduled_explanations: tuple[UnscheduledTaskExplanation, ...]
    placement_explanations: tuple[TaskPlacementExplanation, ...]


class SchedulePlanningDetails(ScheduleExplanations):
    schedule: ScheduleReadResult
    recommendations: tuple[TaskMoveRecommendation, ...]


class PlacementInterval(ReadModel):
    start_at: TaskTimestamp
    end_at: TaskTimestamp

    @model_validator(mode="after")
    def validate_interval(self) -> "PlacementInterval":
        if self.end_at <= self.start_at:
            raise ValueError("Конец интервала должен быть позже начала")
        return self


class SchedulePlacementChange(ReadModel):
    task_id: UUID
    kind: PlacementChangeKind
    before: PlacementInterval | None
    after: PlacementInterval | None
    reason_codes: tuple[ReasonCode, ...]

    @model_validator(mode="after")
    def validate_change(self) -> "SchedulePlacementChange":
        if self.before is None and self.after is None:
            raise ValueError("Изменение должно содержать исходный или итоговый интервал")
        expected = (
            "added"
            if self.before is None
            else "removed"
            if self.after is None
            else "updated"
            if self.before == self.after
            else "moved"
        )
        if self.kind != expected:
            raise ValueError("Тип изменения не соответствует интервалам")
        return self


class ScheduleReplanResponse(SchedulePlanningDetails):
    changes: tuple[SchedulePlacementChange, ...]
