from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictBool

from app.modules.schedule.planning_schemas import ScheduleVersion, ScheduleVersions
from app.modules.tasks.schemas import (
    TaskDate,
    TaskQuery,
    TaskTimestamp,
    TaskVersion,
    _query_integer,
)


class TaskPlacementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned_date: TaskDate
    start_at: TaskTimestamp
    version: TaskVersion
    schedule_versions: ScheduleVersions


class TaskPinRequest(TaskPlacementRequest):
    pass


class TaskMoveRequest(TaskPlacementRequest):
    pass


class TaskStartNowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: TaskVersion
    schedule_versions: ScheduleVersions


class TaskDateLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_date_locked: StrictBool
    version: TaskVersion
    schedule_versions: ScheduleVersions


class TaskUnpinQuery(TaskQuery):
    version: Annotated[TaskVersion, BeforeValidator(_query_integer)]
    schedule_version: Annotated[ScheduleVersion, BeforeValidator(_query_integer)]
