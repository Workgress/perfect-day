"""Reproducible, uninstrumented core benchmark: python -m scripts.benchmark_planner.

Run without coverage/profiling/debuggers. A finite sample reports observed p95, not a
guarantee for every machine. HTTP/DB timing is measured separately in Docker tests.
"""

import argparse
import json
import platform
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from math import ceil
from statistics import median
from time import perf_counter_ns

from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.planner.contracts import (
    FutureDay,
    Interval,
    PlanContext,
    PlanResult,
    PlanSlot,
    TaskKind,
)
from app.modules.planner.engine import build_schedule
from app.modules.planner.replan import replan_remaining_day
from scripts.generate_planner_cases import DAY, at, context, slot, task


def workloads() -> dict[str, PlanContext]:
    kinds: tuple[TaskKind, ...] = ("intellectual", "physical", "creative", "routine")

    def mixed(count: int) -> PlanContext:
        return context(
            *(
                task(
                    i,
                    (5, 17, 30, 45, 60, 90)[i % 6],
                    kinds[i % 4],
                    created_at=at(7) - timedelta(minutes=count - i),
                )
                for i in range(count)
            )
        )

    base = mixed(50)
    critical = replace(
        base, profile=replace(base.profile, birth_utc=base.profile.birth_utc - timedelta(days=12))
    )
    future = tuple(FutureDay(DAY + timedelta(days=offset)) for offset in range(1, 8))
    occupied = occupied_horizon()
    return {
        "mixed_50": base,
        "mixed_100": mixed(100),
        "critical_50_with_horizon": replace(critical, future_days=future),
        "overloaded_100_occupied_horizon": replace(mixed(100), future_days=occupied),
        "critical_50_explicit_transfers": replace(
            critical, future_days=occupied, allow_date_change=True
        ),
    }


def occupied_horizon() -> tuple[FutureDay, ...]:
    days = []
    for offset in range(1, 8):
        day = DAY + timedelta(days=offset)
        start = at(10, day=day)
        resident = task(
            1000 + offset,
            30,
            "routine",
            planned_date=day,
            status="scheduled",
            is_pinned=True,
            pinned_start=start,
        )
        fixed = PlanSlot(
            "task",
            Interval(start, start + timedelta(minutes=30)),
            resident.ref,
            is_pinned=True,
            preservation="pinned",
        )
        days.append(FutureDay(day, (resident,), (fixed,)))
    return tuple(days)


def protected_workload() -> tuple[PlanContext, tuple[PlanSlot, ...]]:
    pinned = task(0, 30, "routine", is_pinned=True, pinned_start=at(10))
    started = task(1, 30, "routine", actual_start=at(9))
    base = workloads()["mixed_50"]
    ctx = replace(
        base,
        tasks=(pinned, started, *base.tasks[2:]),
        now=at(9, 30),
        future_days=occupied_horizon(),
    )
    return ctx, (slot(pinned, 10), slot(started, 14))


def timing_summary(durations: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(durations), 3),
        "median_ms": round(median(durations), 3),
        "p95_ms": round(sorted(durations)[ceil(0.95 * len(durations)) - 1], 3),
        "max_ms": round(max(durations), 3),
    }


def measure(operation: Callable[[], object], samples: int) -> dict[str, float]:
    for _ in range(3):
        operation()
    durations = []
    for _ in range(samples):
        start = perf_counter_ns()
        operation()
        durations.append((perf_counter_ns() - start) / 1_000_000)
    return timing_summary(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Require mixed_50 p95 < 50 ms and all workloads < 2 s",
    )
    args = parser.parse_args()
    if args.samples < 5:
        parser.error("at least five samples are required")
    if sys.gettrace() is not None or sys.getprofile() is not None:
        parser.error("run without coverage, a profiler or debugger")
    results = {}
    scenarios = {}
    for name, ctx in workloads().items():

        def run(selected: PlanContext = ctx) -> PlanResult:
            return build_schedule(selected)

        results[name] = measure(run, args.samples)
        scenarios[name] = {
            "entrypoint": "build_schedule",
            "tasks": len(ctx.tasks),
            "horizon_days": len(ctx.future_days),
            "future_tasks": sum(len(day.tasks) for day in ctx.future_days),
            "allow_date_change": ctx.allow_date_change,
        }
    protected, previous = protected_workload()

    def run_protected() -> object:
        result = replan_remaining_day(protected, previous)
        for saved in previous:
            retained = next(item for item in result.plan.slots if item.task == saved.task)
            if retained.interval != saved.interval:
                raise RuntimeError("Benchmark must retain protected intervals")
        return result

    results["replan_50_protected_occupied_horizon"] = measure(run_protected, args.samples)
    scenarios["replan_50_protected_occupied_horizon"] = {
        "entrypoint": "replan_remaining_day",
        "tasks": len(protected.tasks),
        "horizon_days": len(protected.future_days),
        "future_tasks": 7,
        "protected_intervals": 2,
        "allow_date_change": protected.allow_date_change,
    }
    print(
        json.dumps(
            {
                "algorithm_version": ALGORITHM_VERSION,
                "python": platform.python_version(),
                "platform": platform.system(),
                "processor": platform.processor(),
                "samples": args.samples,
                "warmups": 3,
                "scenarios": scenarios,
                "results": results,
            },
            indent=2,
        )
    )
    failed = results["mixed_50"]["p95_ms"] >= 50 or any(
        result["p95_ms"] >= 2000 for result in results.values()
    )
    return int(args.enforce and failed)


if __name__ == "__main__":
    raise SystemExit(main())
