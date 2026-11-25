from app.core.errors import AppError


class TaskNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(404, "TASK_NOT_FOUND", "Задача не найдена")


class TaskVersionConflictError(AppError):
    def __init__(self, expected_version: int, current_version: int) -> None:
        super().__init__(
            409,
            "TASK_VERSION_CONFLICT",
            "Задача уже изменена, обновите данные",
            {"expected_version": expected_version, "current_version": current_version},
        )
