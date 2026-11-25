from pydantic import BaseModel, ConfigDict

from app.modules.schedule.planning_schemas import ScheduleVersions
from app.modules.tasks.schemas import TaskDate, TaskTimestamp, TaskVersion


class TaskPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned_date: TaskDate
    start_at: TaskTimestamp
    version: TaskVersion
    schedule_versions: ScheduleVersions
