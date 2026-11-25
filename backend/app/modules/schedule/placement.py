from dataclasses import dataclass, replace
from datetime import timedelta

from app.core.time import parse_timezone
from app.modules.planner.constraints import check_placement, overlaps, placement_checker
from app.modules.planner.contracts import Interval, PlanContext, PlanSlot, PlanTask
from app.modules.planner.policy import day_policy, prepare_policy_day
from app.modules.planner.replan import preserve_reservations
from app.modules.schedule.planning_schemas import PlacementRefusal

MESSAGES = {
    "TASK_INACTIVE": "Выполненную или пропущенную задачу нельзя разместить.",
    "TASK_PINNED": "Время задачи закреплено. Сначала снимите закрепление.",
    "TASK_STARTED": "Задача уже начата. Её сохранённый интервал нельзя изменить.",
    "TASK_ALREADY_RESERVED": "Сохранённый исторический интервал задачи нельзя изменить.",
    "DURATION_MISMATCH": "Длительность интервала не совпадает с длительностью задачи.",
    "OUTSIDE_WORK_WINDOW": "Интервал выходит за рабочее время профиля.",
    "PAST_START": "Выбранное время начала уже прошло.",
    "DEADLINE_EXCEEDED": "Задача закончится позже установленного дедлайна.",
    "INTERVAL_OCCUPIED": "Выбранный интервал занят.",
    "INSUFFICIENT_BREAK": "Между задачами недостаточно времени для обязательного перерыва.",
    "DAY_CAPACITY_EXCEEDED": "Размещение превысит допустимую нагрузку дня.",
    "INTENSITY_CAPACITY_EXCEEDED": "Размещение превысит лимит интенсивной работы на этот день.",
    "CRITICAL_REST_UNAVAILABLE": "Не удалось выделить обязательный отдых в критический день.",
}


@dataclass(frozen=True, slots=True)
class PlacementRejection:
    code: str
    message: str
    conflict: PlanSlot | None = None


def selected_placement_refusals(
    context: PlanContext, task: PlanTask, interval: Interval, previous: tuple[PlanSlot, ...]
) -> tuple[PlacementRejection, ...]:
    preserved = preserve_reservations(context, previous)
    protected = next((slot for slot in preserved if slot.task == task.ref), None)
    if task.status in {"done", "skipped"}:
        return (PlacementRejection(code="TASK_INACTIVE", message=MESSAGES["TASK_INACTIVE"]),)
    if protected is not None and protected.interval != interval:
        code = (
            "TASK_STARTED"
            if protected.preservation == "started"
            else "TASK_PINNED"
            if protected.preservation == "pinned"
            else "TASK_ALREADY_RESERVED"
        )
        return (PlacementRejection(code=code, message=MESSAGES[code]),)
    if task.is_pinned and interval.start != task.pinned_start:
        return (PlacementRejection(code="TASK_PINNED", message=MESSAGES["TASK_PINNED"]),)
    if interval.end - interval.start != timedelta(minutes=task.duration_min):
        return (
            PlacementRejection(code="DURATION_MISMATCH", message=MESSAGES["DURATION_MISMATCH"]),
        )
    known = {item.ref: item for item in context.tasks}
    by_task = {slot.task: slot for slot in preserved if slot.task is not None}
    occupied = tuple(
        slot
        for slot in previous
        if slot.task != task.ref
        and (slot.task is not None or slot.kind != "break" or slot.interval.start <= context.now)
        and (slot.task is None or known[slot.task].status != "skipped" or slot.task in by_task)
    )
    occupied = tuple(
        by_task.get(slot.task, slot) if slot.task is not None else slot for slot in occupied
    )
    occupied = (
        *occupied,
        *(
            slot
            for slot in preserved
            if slot.task != task.ref
            and not any(
                (slot.task is not None and slot.task == existing.task)
                or (
                    slot.task is None
                    and slot.kind == existing.kind
                    and slot.interval == existing.interval
                )
                for existing in occupied
            )
        ),
    )
    selected = replace(task, is_pinned=False, pinned_start=None)
    movable = tuple(slot for slot in occupied if slot.task is not None and slot.task not in by_task)
    fixed = tuple(
        replace(slot, preservation="system") if slot.task is None else slot
        for slot in occupied
        if slot.task is None or slot.task in by_task
    )
    slots = (*fixed, protected) if protected is not None else fixed
    prepared_context = replace(
        context,
        tasks=tuple(
            selected if item.ref == task.ref and protected is None else item
            for item in context.tasks
        ),
        fixed_slots=slots,
        include_profile_lunch=not any(slot.kind == "lunch" for slot in slots),
    )
    prepared, shortfall = prepare_policy_day(
        prepared_context,
        day_policy(context.profile, context.day),
        occupied_intervals=(*tuple(slot.interval for slot in movable), interval),
    )
    if protected is not None:
        placement_checker(prepared, placed_slots=movable)
        return ()
    codes: tuple[str, ...]
    if shortfall:
        codes = ("CRITICAL_REST_UNAVAILABLE",)
    else:
        codes = check_placement(prepared, selected, interval, placed_slots=movable).reasons
    tz = parse_timezone(context.profile.timezone)
    refusals = []
    for code in codes:
        message = MESSAGES.get(code, "Размещение нарушает ограничения расписания.")
        conflict = None
        if code == "INTERVAL_OCCUPIED":
            conflict = next(
                (slot for slot in (*prepared.slots, *movable) if overlaps(slot.interval, interval)),
                None,
            )
            if conflict is not None:
                start, end = (
                    conflict.interval.start.astimezone(tz),
                    conflict.interval.end.astimezone(tz),
                )
                label = {
                    "task": "задачей",
                    "lunch": "обедом",
                    "break": "перерывом",
                    "rest": "отдыхом",
                }[conflict.kind]
                message = f"Интервал занят {label} с {start:%H:%M %z} до {end:%H:%M %z}."
        refusals.append(
            PlacementRejection(
                code=code,
                message=message,
                conflict=conflict,
            )
        )
    return tuple(refusals)


def check_selected_placement(
    context: PlanContext, task: PlanTask, interval: Interval, previous: tuple[PlanSlot, ...]
) -> tuple[PlacementRefusal, ...]:
    return tuple(
        PlacementRefusal(
            code=item.code,
            message=item.message,
            conflicting_task_id=item.conflict.task.task_id
            if item.conflict is not None and item.conflict.task is not None
            else None,
        )
        for item in selected_placement_refusals(context, task, interval, previous)
    )
