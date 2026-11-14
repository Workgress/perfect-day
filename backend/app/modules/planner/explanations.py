"""Russian templates and measured explanations, kept outside task selection."""

from dataclasses import replace
from datetime import date

from app.core.time import parse_timezone
from app.modules.biorhythm import engine as biorhythm
from app.modules.biorhythm.types import Cycle
from app.modules.planner.contracts import PlanContext, PlanSlot
from app.modules.planner.energy import score_interval
from app.modules.planner.policy import DayPolicy

CYCLE_NAMES = {
    Cycle.INTELLECTUAL: "Интеллектуальный",
    Cycle.PHYSICAL: "Физический",
    Cycle.EMOTIONAL: "Эмоциональный",
}
PEAK_CODES = {
    Cycle.INTELLECTUAL: "INTELLECTUAL_PEAK",
    Cycle.PHYSICAL: "PHYSICAL_PEAK",
    Cycle.EMOTIONAL: "EMOTIONAL_PEAK",
}
TEMPLATES = {
    "ENERGY_RANKED": "Время выбрано по оценке энергии и ограничениям расписания.",
    "LOW_ENERGY_ROUTINE": "Рутинная задача размещена с предпочтением менее энергичных окон.",
    "PREFERRED_TIME": "Учтено предпочтительное время начала.",
    "PINNED_BY_USER": "Начало закреплено пользователем.",
    "TYPE_REPETITION": "При оценке учтено повторение соседнего типа деятельности.",
    "CIRCADIAN_WINDOW": "Интервал включает высокое окно суточного профиля энергии.",
    "BREAK_AFTER_LONG_WORK": "Перерыв после длительной непрерывной работы.",
    "BETWEEN_INTELLECTUAL_TASKS": "Перерыв между интеллектуальными задачами.",
    "BETWEEN_INTENSIVE_TASKS": "Перерыв между интенсивными задачами.",
    "CRITICAL_DAY_REST": "Отдых для снижения нагрузки в критический день.",
    "REST_BLOCK": "Запланированный отдых.",
    "LUNCH": "Перерыв на обед.",
    "BREAK": "Перерыв между задачами.",
}


def explain_move(slot: PlanSlot, from_date: date) -> PlanSlot:
    return replace(
        slot,
        reason_codes=(*slot.reason_codes, "MOVED_FROM_CRITICAL_DAY"),
        explanation=f"Перенос с критического дня {from_date.isoformat()}. {slot.explanation or ''}",
    )


def explain_slots(
    context: PlanContext, slots: tuple[PlanSlot, ...], policy: DayPolicy
) -> tuple[PlanSlot, ...]:
    """Enrich new slots only; saved explanations and all other fixed metadata are immutable."""
    tasks = {task.ref: task for task in context.tasks}
    tz = parse_timezone(context.profile.timezone)
    result = []
    for slot in slots:
        if slot in context.fixed_slots:
            result.append(slot)
            continue
        codes = list(slot.reason_codes)
        details = []
        if slot.is_pinned:
            codes.append("PINNED_BY_USER")
        elif slot.task is not None:
            task = tasks[slot.task]
            rating = score_interval(context.profile, task, slot.interval)
            if rating.cycle is None:
                codes.append("LOW_ENERGY_ROUTINE")
            else:
                assert rating.cycle_mean is not None
                details.append(
                    f"{CYCLE_NAMES[rating.cycle]} биоритм: "
                    f"среднее за интервал {biorhythm.percent(rating.cycle_mean):g}%."
                )
                if rating.cycle_mean >= 0.5:
                    codes.append(PEAK_CODES[rating.cycle])
                    details.append("Среднее значение биоритма находится в фазе пика.")
                if rating.peak_fraction > 0:
                    codes.append("CIRCADIAN_WINDOW")
            if rating.preference_bonus:
                codes.append("PREFERRED_TIME")
        else:
            if slot.kind == "rest":
                codes.append("CRITICAL_DAY_REST" if policy.rest_count else "REST_BLOCK")
            else:
                codes.append(slot.kind.upper())
        codes = list(dict.fromkeys(codes))
        start, end = slot.interval.start.astimezone(tz), slot.interval.end.astimezone(tz)
        # Offsets disambiguate repeated clocks and intervals crossing a DST transition.
        clock = f"{start:%H:%M %z}–{end:%H:%M %z}"
        text = " ".join([*(TEMPLATES[code] for code in codes if code in TEMPLATES), *details])
        result.append(replace(slot, reason_codes=tuple(codes), explanation=f"{clock}. {text}"))
    return tuple(result)
