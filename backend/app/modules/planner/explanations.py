"""Russian templates and measured explanations, kept outside task selection."""

from dataclasses import replace
from datetime import date, datetime

from app.core.time import parse_timezone
from app.modules.biorhythm import engine as biorhythm
from app.modules.biorhythm.types import Cycle
from app.modules.planner.contracts import PlanContext, PlanSlot, UnscheduledTask
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
CHRONOTYPE_NAMES = {"lark": "жаворонок", "dove": "голубь", "owl": "сова"}
UNSCHEDULED_MESSAGES = {
    "NO_AVAILABLE_TIME": "В оставшейся части рабочего дня нет доступного времени.",
    "NO_CONTIGUOUS_WINDOW": "Нет непрерывного окна нужной длительности.",
    "OUTSIDE_WORK_WINDOW": "Проверенные интервалы выходят за рабочее время.",
    "PAST_START": "Время начала проверенных интервалов уже прошло.",
    "INTERVAL_OCCUPIED": "Часть проверенных окон занята задачами или перерывами.",
    "INSUFFICIENT_BREAK": "Не хватает времени для обязательного перерыва между задачами.",
    "DEADLINE_EXCEEDED": "Проверенные интервалы заканчиваются позже дедлайна.",
    "DAY_CAPACITY_EXCEEDED": "Размещение превышает допустимую нагрузку дня.",
    "INTENSITY_CAPACITY_EXCEEDED": "Размещение превышает лимит интенсивной работы дня.",
    "CRITICAL_REST_UNAVAILABLE": "Не удалось выделить обязательный отдых в критический день.",
}


def unscheduled_explanation(
    day: date, reason_codes: tuple[str, ...], duration_min: int | None = None
) -> str:
    text = [f"На {day.isoformat()} не удалось подобрать время для задачи."]
    if duration_min is not None:
        text.append(f"Нужен непрерывный интервал {duration_min} мин.")
    reasons = [
        UNSCHEDULED_MESSAGES[code]
        for code in dict.fromkeys(reason_codes)
        if code in UNSCHEDULED_MESSAGES
    ]
    if reasons:
        text.extend(["Причины отказов при проверке вариантов:", *reasons])
    elif "NO_FEASIBLE_INTERVAL" not in reason_codes:
        text.append("Сохранённые причины не содержат подробного пояснения.")
    if "DATE_CHANGE_FORBIDDEN" in reason_codes:
        text.append("Перенос даты запрещён: задача оставлена на выбранной дате без времени.")
    return " ".join(text)


def explain_unscheduled(
    context: PlanContext, items: tuple[UnscheduledTask, ...]
) -> tuple[UnscheduledTask, ...]:
    tasks = {task.ref: task for task in context.tasks}
    return tuple(
        replace(
            item,
            explanation=unscheduled_explanation(
                context.day, item.reason_codes, tasks[item.task].duration_min
            ),
        )
        for item in items
    )


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
                assert rating.circadian_mean is not None
                details.append(
                    f"Среднее значение суточного профиля: {rating.circadian_mean * 100:.1f}% "
                    f"(хронотип: {CHRONOTYPE_NAMES[context.profile.chronotype]})."
                )
            if rating.preference_bonus:
                codes.append("PREFERRED_TIME")
                assert task.preferred_start is not None
                details.append(f"Предпочтительное начало: {task.preferred_start:%H:%M}.")
        else:
            if slot.kind == "rest":
                codes.append("CRITICAL_DAY_REST" if policy.rest_count else "REST_BLOCK")
            else:
                codes.append(slot.kind.upper())
        if slot.task is not None:
            task = tasks[slot.task]
            details.append(f"Длительность: {task.duration_min} мин.")
            if task.deadline is not None:
                if isinstance(task.deadline, datetime):
                    details.append(f"Дедлайн: {task.deadline.astimezone(tz):%d.%m.%Y %H:%M %z}.")
                else:
                    details.append(f"Дедлайн: до конца {task.deadline.isoformat()}.")
        codes = list(dict.fromkeys(codes))
        start, end = slot.interval.start.astimezone(tz), slot.interval.end.astimezone(tz)
        # Offsets disambiguate repeated clocks and intervals crossing a DST transition.
        clock = f"{start:%H:%M %z}–{end:%H:%M %z}"
        text = " ".join([*(TEMPLATES[code] for code in codes if code in TEMPLATES), *details])
        result.append(replace(slot, reason_codes=tuple(codes), explanation=f"{clock}. {text}"))
    return tuple(result)
