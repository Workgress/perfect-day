"""Day-level recommendations based on measured load and calculated cycle values."""

from app.modules.biorhythm import engine as biorhythm
from app.modules.planner.config import TASK_CYCLES
from app.modules.planner.contracts import PlanContext, PlanResult, PlanTask, PlanWarning, TaskRef
from app.modules.planner.explanations import CYCLE_NAMES, PEAK_CODES
from app.modules.planner.policy import DayPolicy


def overloaded(result: PlanResult) -> bool:
    return (
        bool(result.unscheduled)
        or result.metrics.planned_min * 100 > result.metrics.capacity_min * 85
    )


def day_recommendations(
    context: PlanContext, result: PlanResult, policy: DayPolicy, rest_shortfall: int
) -> tuple[PlanWarning, ...]:
    warnings = []
    if policy.critical.level:
        warnings.append(
            PlanWarning(
                "CRITICAL_DAY",
                message=f"Критических циклов: {policy.critical.level}. "
                f"Коэффициент нагрузки: {result.metrics.load_factor:g}; "
                f"доступно {result.metrics.capacity_min} мин.",
                level="critical" if policy.critical.level >= 2 else "warning",
            )
        )
    for cycle, value in policy.cycle_values:
        if cycle in policy.minimum_cycles or value >= 0.5:
            minimum = cycle in policy.minimum_cycles
            warnings.append(
                PlanWarning(
                    "CYCLE_MINIMUM" if minimum else PEAK_CODES[cycle],
                    message=f"{CYCLE_NAMES[cycle]} биоритм в местные 12:00: "
                    f"{biorhythm.percent(value):g}%. "
                    + ("Рекомендуется снизить нагрузку." if minimum else "Фаза пика."),
                    level="warning" if minimum else "info",
                )
            )
    if rest_shortfall:
        warnings.append(
            PlanWarning(
                "CRITICAL_REST_UNAVAILABLE",
                message=f"Не удалось выделить {rest_shortfall} блок(а) отдыха по 30 мин. "
                "Сохранённые интервалы защищены; новые задачи не добавлены.",
                level="critical",
            )
        )
    if overloaded(result):
        warnings.append(
            PlanWarning(
                "OVERLOAD",
                message=f"Запланировано {result.metrics.planned_min} из "
                f"{result.metrics.capacity_min} доступных мин; "
                f"не размещено задач: {len(result.unscheduled)}. "
                "Рекомендуется перенести часть нагрузки.",
                level="warning",
            )
        )
    tasks = {task.ref: task for task in context.tasks}
    consecutive = 0
    for slot in result.slots:
        if slot.task is None or tasks[slot.task].status == "skipped":
            continue
        task = tasks[slot.task]
        consecutive = consecutive + 1 if task.kind == "intellectual" else 0
        if consecutive == 4:
            warnings.append(
                PlanWarning(
                    "ALTERNATING_TYPES",
                    message="Подряд запланировано больше трёх интеллектуальных задач. "
                    "Рекомендуется чередовать типы деятельности.",
                    level="warning",
                )
            )
            break
    return tuple(warnings)


def critical_move_unavailable(task: TaskRef) -> PlanWarning:
    return PlanWarning(
        "CRITICAL_MOVE_UNAVAILABLE",
        task=task,
        message="Подходящий день переноса не подтверждён в переданных снимках "
        "следующих семи дней. Задача остаётся на исходной дате.",
        level="warning",
    )


def move_recommendation(
    task: PlanTask, target: PlanResult, policy: DayPolicy, *, automatic: bool
) -> str:
    action = "Предложен автоматический перенос" if automatic else "Рекомендуется перенос"
    cycle = TASK_CYCLES.get(task.kind)
    cycle_text = (
        f" {CYCLE_NAMES[cycle]} биоритм в местные 12:00: "
        f"{biorhythm.percent(policy.value(cycle)):g}%."
        if cycle is not None
        else ""
    )
    return (
        f"{action} на {target.day.isoformat()}: задача {task.duration_min} мин помещается целиком; "
        f"нагрузка дня после размещения {target.metrics.planned_min} из "
        f"{target.metrics.capacity_min} доступных мин.{cycle_text}"
    )
