from app.core.time import parse_timezone
from app.modules.planner.contracts import PlanResult
from app.modules.planner.explanations import unscheduled_explanation
from app.modules.schedule.planning_schemas import (
    ScheduleExplanations,
    TaskPlacementExplanation,
    UnscheduledTaskExplanation,
)

PRESERVATION_REASONS = {
    "pinned": ("PINNED_BY_USER", "Время закреплено пользователем и сохранено при пересчёте."),
    "started": ("TASK_STARTED", "Задача уже начата; сохранён её исходный интервал."),
    "past": ("PAST_INTERVAL_PRESERVED", "Прошедший интервал сохранён как история расписания."),
    "done": ("TASK_COMPLETED", "Задача выполнена; сохранён её исходный интервал."),
}


def schedule_explanations(plan: PlanResult) -> ScheduleExplanations:
    tz = parse_timezone(plan.timezone)
    placements = []
    for slot in plan.slots:
        if slot.task is None:
            continue
        if slot.task.task_id is None:
            raise ValueError("Explanation requires a persisted task ID")
        preservation = slot.preservation or ("pinned" if slot.is_pinned else None)
        codes = slot.reason_codes or ("SAVED_PLACEMENT",)
        text = slot.explanation
        if preservation in PRESERVATION_REASONS:
            code, message = PRESERVATION_REASONS[preservation]
            codes = (code,)
            text = message
        if not text or not text.strip():
            text = "Интервал взят из сохранённого расписания; подробная причина выбора недоступна."
        start, end = slot.interval.start.astimezone(tz), slot.interval.end.astimezone(tz)
        duration = (slot.interval.end - slot.interval.start).total_seconds() / 60
        if preservation is not None or not slot.explanation or not slot.explanation.strip():
            text = f"{start:%H:%M %z}–{end:%H:%M %z}. {text} Длительность: {duration:g} мин."
        placements.append(
            TaskPlacementExplanation(
                task_id=slot.task.task_id,
                planned_date=plan.day,
                start_at=slot.interval.start,
                end_at=slot.interval.end,
                preservation=preservation,
                reason_codes=codes,
                explanation=text,
            )
        )
    unplaced = []
    for item in plan.unscheduled:
        if item.task.task_id is None:
            raise ValueError("Explanation requires a persisted task ID")
        unplaced.append(
            UnscheduledTaskExplanation(
                task_id=item.task.task_id,
                planned_date=plan.day,
                reason_codes=item.reason_codes,
                explanation=item.explanation
                or unscheduled_explanation(plan.day, item.reason_codes),
            )
        )
    return ScheduleExplanations(
        placement_explanations=tuple(placements), unscheduled_explanations=tuple(unplaced)
    )
