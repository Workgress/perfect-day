from app.modules.tasks.errors import TaskVersionConflictError
from app.modules.tasks.models import Task


def check_task_version(task: Task, expected_version: int) -> None:
    if task.version != expected_version:
        raise TaskVersionConflictError(expected_version, task.version)
