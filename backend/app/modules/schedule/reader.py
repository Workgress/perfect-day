from dataclasses import asdict
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.planner.contracts import TaskRef
from app.modules.schedule.planning_schemas import TaskMoveRecommendation
from app.modules.schedule.read_models import (
    ScheduleReadMetrics,
    ScheduleReadMove,
    ScheduleReadResult,
    ScheduleReadSlot,
    ScheduleReadUnscheduled,
    ScheduleReadWarning,
)
from app.modules.schedule.repository import ScheduleRepository


def _task_id(ref: TaskRef) -> UUID:
    if ref.task_id is None:
        raise AppError(
            409, "SCHEDULE_RESULT_INCOMPLETE", "Сохранённый результат расписания неполон"
        )
    return ref.task_id


class ScheduleReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ScheduleRepository(session)

    async def get_recommendations(
        self, user_id: UUID, day: date
    ) -> tuple[TaskMoveRecommendation, ...] | None:
        row = (await self.repository.active(user_id, (day,))).get(day)
        if row is None:
            return None
        plan = await self.repository.result(user_id, row.id)
        if plan is None:
            return None
        return tuple(
            TaskMoveRecommendation(
                task_id=_task_id(item.task),
                from_date=item.from_date,
                to_date=item.to_date,
                reason_code=item.reason_code,
                explanation=item.explanation,
            )
            for item in plan.recommendations
        )

    async def get(self, user_id: UUID, day: date) -> ScheduleReadResult | None:
        row = (await self.repository.active(user_id, (day,))).get(day)
        if row is None:
            return None
        plan = await self.repository.result(user_id, row.id)
        if plan is None:
            return None
        return ScheduleReadResult(
            id=row.id,
            planned_date=plan.day,
            timezone=plan.timezone,
            version=row.version,
            algorithm_version=plan.algorithm_version,
            generated_at=row.generated_at,
            slots=tuple(
                ScheduleReadSlot(
                    id=slot.id,
                    kind=slot.kind.value,
                    task_id=slot.task_id,
                    start_at=slot.start_at,
                    end_at=slot.end_at,
                    is_pinned=slot.is_pinned,
                    reason_codes=tuple(slot.reason_codes),
                    explanation=slot.explanation,
                )
                for slot in row.slots
            ),
            unscheduled=tuple(
                ScheduleReadUnscheduled(task_id=_task_id(item.task), reason_codes=item.reason_codes)
                for item in plan.unscheduled
            ),
            metrics=ScheduleReadMetrics(**asdict(plan.metrics)),
            warnings=tuple(
                ScheduleReadWarning(
                    code=item.code,
                    message=item.message,
                    level=item.level,
                    task_id=item.task.task_id if item.task is not None else None,
                    target_date=item.target_date,
                )
                for item in plan.warnings
            ),
            moves=tuple(
                ScheduleReadMove(
                    task_id=_task_id(item.task),
                    from_date=item.from_date,
                    to_date=item.to_date,
                    reason_code=item.reason_code,
                )
                for item in plan.moves
            ),
        )
