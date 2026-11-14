"""Run python -m scripts.generate_planner_cases [--check] from backend."""

import argparse
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import TypeAdapter

from app.core.time import parse_timezone
from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.planner.contracts import (
    FutureDay,
    Interval,
    PlanContext,
    PlanProfile,
    PlanResult,
    PlanSlot,
    PlanTask,
    ReplanResult,
    TaskKind,
    TaskRef,
)
from app.modules.planner.documentation import rules
from app.modules.planner.engine import build_schedule
from app.modules.planner.replan import replan_remaining_day
from scripts.generate_biorhythm_vectors import FIXTURES_DIR, render

DAY = date(2026, 11, 14)
CONTEXT = TypeAdapter(PlanContext)
SLOTS = TypeAdapter(tuple[PlanSlot, ...])
PLAN = TypeAdapter(PlanResult)
REPLAN = TypeAdapter(ReplanResult)


def at(hour: int, minute: int = 0, *, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


def task(index: int = 0, minutes: int = 30, kind: TaskKind = "routine", **fields: Any) -> PlanTask:
    return replace(PlanTask(TaskRef(task_id=UUID(int=index + 1)), kind, minutes, DAY), **fields)


def context(*tasks: PlanTask, elapsed: float = 2, **fields: Any) -> PlanContext:
    profile = PlanProfile(
        at(12) - timedelta(days=elapsed),
        "UTC",
        "dove",
        time(8),
        time(18),
        time(23),
        work_days=(1, 2, 3, 4, 5, 6, 7),
    )
    return replace(PlanContext(profile, DAY, at(7), tasks, "replan"), **fields)


def slot(item: PlanTask, hour: int, minute: int = 0) -> PlanSlot:
    start = at(hour, minute)
    return PlanSlot(
        "task",
        Interval(start, start + timedelta(minutes=item.duration_min)),
        item.ref,
        is_pinned=item.is_pinned,
        score=0.7,
        explanation="Сохранённый интервал",
    )


@dataclass(frozen=True)
class Case:
    id: str
    tags: tuple[str, ...]
    context: PlanContext
    previous: tuple[PlanSlot, ...] | None = None

    def document(self) -> dict[str, Any]:
        if self.previous is None:
            entry, expected = (
                "build_schedule",
                PLAN.dump_python(build_schedule(self.context), mode="json"),
            )
        else:
            entry = "replan_remaining_day"
            expected = REPLAN.dump_python(
                replan_remaining_day(self.context, self.previous), mode="json"
            )
        return {
            "id": self.id,
            "tags": list(self.tags),
            "entrypoint": entry,
            "input": {
                "context": CONTEXT.dump_python(self.context, mode="json"),
                "previous_slots": SLOTS.dump_python(self.previous, mode="json")
                if self.previous is not None
                else None,
            },
            "expected": expected,
        }


def cases() -> tuple[Case, ...]:
    result = []
    kinds: tuple[TaskKind, ...] = ("intellectual", "physical", "creative", "routine")
    mixed = tuple(task(i, 17 + i * 5, kind) for i, kind in enumerate(kinds))
    for chronotype in ("lark", "dove", "owl"):
        ctx = context(*mixed)
        result.append(
            Case(
                f"chronotype-{chronotype}",
                ("chronotype", chronotype),
                replace(ctx, profile=replace(ctx.profile, chronotype=chronotype)),
            )
        )
    for zone in ("UTC", "Asia/Yekaterinburg", "Europe/Berlin", "America/New_York"):
        ctx = context(*mixed)
        result.append(
            Case(
                f"timezone-{zone}",
                ("timezone", "whole_tasks"),
                replace(ctx, profile=replace(ctx.profile, timezone=zone)),
            )
        )
    for label, elapsed in (
        ("single", 11.5),
        ("single-minimum", 14),
        ("double", 966),
        ("double-minimum", 322),
        ("triple", 644),
        ("minimum", 20),
    ):
        result.append(
            Case(
                f"load-{label}",
                ("critical", "load", label),
                context(task(minutes=5), elapsed=elapsed),
            )
        )
    pinned = task(is_pinned=True, pinned_start=at(14, 7))
    result.append(Case("off-grid-pin", ("pin", "whole_tasks"), context(pinned, task(1, 17))))
    result.append(
        Case(
            "preferred-start",
            ("preferred_time",),
            context(task(kind="creative", preferred_start=time(9))),
        )
    )
    result.append(
        Case(
            "expired-deadline",
            ("deadline", "overflow"),
            context(task(deadline=DAY - timedelta(days=1))),
        )
    )
    result.append(Case("inclusive-deadline", ("deadline",), context(task(deadline=DAY))))
    for label, kind, minutes, second_start in (
        ("intellectual-pair", "intellectual", 60, time(9, 30)),
        ("continuous-100", "routine", 100, time(10)),
        ("continuous-121", "routine", 121, time(10, 45)),
        ("intensity-gap-10", "physical", 45, time(8, 55)),
    ):
        first = task(minutes=minutes, kind=cast(TaskKind, kind), is_pinned=True, pinned_start=at(8))
        second = task(
            1,
            5,
            "intellectual",
            is_pinned=True,
            pinned_start=at(second_start.hour, second_start.minute),
        )
        result.append(Case(f"break-{label}", ("break", label), context(first, second)))
    for minutes in (85, 86):
        ctx = context(task(minutes=minutes, is_pinned=True, pinned_start=at(8)))
        result.append(
            Case(
                f"load-threshold-{minutes}",
                ("overload", "threshold"),
                replace(
                    ctx, profile=replace(ctx.profile, work_end=time(9, 40), lunch_duration_min=0)
                ),
            )
        )
    result.append(Case("partial-overflow", ("overflow",), context(task(minutes=480), task(1, 17))))
    result.append(Case("empty-day", ("empty",), context()))
    first, started, done = task(minutes=60), task(1, 60), task(2, status="done")
    pinned = replace(pinned, ref=TaskRef(task_id=UUID(int=4)))
    ctx = context(first, started, done, pinned, task(4, 17), now=at(10))
    result.append(
        Case(
            "replan-protected",
            ("replan", "history", "pin", "done", "started"),
            ctx,
            (slot(first, 8), slot(started, 9, 30), slot(pinned, 14, 7), slot(done, 15)),
        )
    )
    old = task()
    new_pin = replace(old, is_pinned=True, pinned_start=at(14, 7))
    result.append(
        Case("replan-manual-pin", ("replan", "pin"), context(new_pin, now=at(10)), (slot(old, 13),))
    )
    skipped = task(minutes=60, kind="intellectual", status="skipped")
    result.append(
        Case(
            "replan-skipped-history",
            ("replan", "skipped", "history"),
            context(skipped, task(1), now=at(10)),
            (slot(skipped, 8),),
        )
    )
    result.append(
        Case("replan-future-deletion", ("replan", "deleted"), context(now=at(10)), (slot(old, 14),))
    )
    future = FutureDay(DAY + timedelta(days=1))
    incoming = task(minutes=60, kind="intellectual")
    result.append(
        Case(
            "critical-transfer",
            ("critical", "transfer"),
            context(incoming, elapsed=14, future_days=(future,)),
        )
    )
    result.append(
        Case(
            "deadline-blocks-transfer",
            ("critical", "deadline", "transfer"),
            context(replace(incoming, deadline=DAY), elapsed=14, future_days=(future,)),
        )
    )
    result.append(
        Case(
            "overflow-advice",
            ("overflow", "advice", "replan"),
            context(old, now=at(20), future_days=(future,)),
            (),
        )
    )
    for day, name in ((date(2026, 3, 29), "gap"), (date(2026, 10, 25), "fold")):
        ctx = context()
        profile = replace(
            ctx.profile,
            birth_utc=at(12, day=day) - timedelta(days=2),
            timezone="Europe/Berlin",
            work_start=time.min,
            work_end=time(5),
            lunch_duration_min=0,
        )
        tasks = tuple(
            replace(task(i, 17), planned_date=day, ref=TaskRef(task_index=i)) for i in range(3)
        )
        ctx = PlanContext(profile, day, at(0, day=day) - timedelta(days=1), tasks, "preview")
        result.append(Case(f"preview-dst-{name}", ("preview", "DST", name), ctx))
        if name == "gap":
            long = replace(tasks[0], duration_min=120)
            result.append(
                Case(
                    "preview-dst-gap-long-task",
                    ("preview", "DST", "wall_duration"),
                    replace(ctx, tasks=(long,)),
                )
            )
    return tuple(result)


def document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "algorithm_version": ALGORITHM_VERSION,
        "interface": "Internal immutable snapshots; not task CRUD JSON. "
        "HTTP preview uses original task_index and local clocks.",
        "comparison": {
            "float_absolute_tolerance": 1e-12,
            "intervals_and_codes": "exact",
            "float_rounding_for_export_only": 12,
        },
        "rules": rules(),
        "http_preview_cases": http_preview_cases(),
        "cases": [case.document() for case in cases()],
    }


def http_preview_cases() -> list[dict[str, Any]]:
    result = []
    for name, zone, durations in (
        ("complete-preview", "UTC", (17, 25)),
        ("partial-preview", "UTC", (17, 480)),
        ("local-preview", "Asia/Yekaterinburg", (17, 25)),
        ("spring-forward-preview", "Europe/Berlin", (120,)),
    ):
        tasks = tuple(
            replace(task(i, minutes), ref=TaskRef(task_index=i))
            for i, minutes in enumerate(durations)
        )
        base = context()
        ctx = PlanContext(replace(base.profile, timezone=zone), DAY, base.now, tasks, "preview")
        if name == "spring-forward-preview":
            day = date(2026, 3, 29)
            ctx = replace(
                ctx,
                day=day,
                now=at(0, day=day),
                tasks=tuple(replace(task, planned_date=day) for task in tasks),
                profile=replace(
                    ctx.profile,
                    birth_utc=at(12, day=day) - timedelta(days=2),
                    work_start=time.min,
                    work_end=time(5),
                ),
            )
        plan = build_schedule(ctx)
        tz = parse_timezone(zone)
        result.append(
            {
                "id": name,
                "now": ctx.now.isoformat().replace("+00:00", "Z"),
                "profile_patch": {
                    "birth_date": ctx.profile.birth_utc.date().isoformat(),
                    "birth_time": "12:00:00",
                    "chronotype": ctx.profile.chronotype,
                    "timezone": zone,
                    "work_start": ctx.profile.work_start.isoformat(),
                    "work_end": ctx.profile.work_end.isoformat(),
                    "sleep_time": "23:00:00",
                },
                "request": {
                    "planned_date": ctx.day.isoformat(),
                    "tasks": [
                        {
                            "title": f"Задача {i}",
                            "type": task.kind,
                            "duration_min": task.duration_min,
                        }
                        for i, task in enumerate(tasks)
                    ],
                },
                "expected": {
                    "planned_date": ctx.day.isoformat(),
                    "timezone": zone,
                    "slots": [
                        {
                            "task_index": item.task.task_index,
                            "start_time": item.interval.start.astimezone(tz).strftime("%H:%M:%S"),
                            "end_time": item.interval.end.astimezone(tz).strftime("%H:%M:%S"),
                            "explanation": item.explanation,
                        }
                        for item in plan.slots
                        if item.task is not None
                    ],
                    "unscheduled_task_indexes": sorted(
                        item.task.task_index
                        for item in plan.unscheduled
                        if item.task.task_index is not None
                    ),
                },
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without writing")
    args = parser.parse_args()
    path = FIXTURES_DIR / "planner_cases.json"
    content = render(document())
    if args.check:
        if not path.exists() or path.read_bytes() != content:
            print("Outdated planner_cases.json; regenerate without --check")
            return 1
        print("Planner fixtures are current")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        print(f"Wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
