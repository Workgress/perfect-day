"""Reproducible, uninstrumented core benchmark: python -m scripts.benchmark_planner.

Run without coverage/profiling/debuggers. A finite sample reports observed p95, not a
guarantee for every machine. HTTP/DB timing is measured separately in Docker tests.
"""

import argparse
import json
import platform
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from math import ceil
from statistics import median
from time import perf_counter_ns

from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.planner.contracts import FutureDay, PlanContext, PlanResult, TaskKind
from app.modules.planner.engine import build_schedule
from scripts.generate_planner_cases import DAY, context, task


def workloads() -> dict[str, PlanContext]:
    kinds: tuple[TaskKind, ...] = ("intellectual", "physical", "creative", "routine")

    def mixed(count: int) -> PlanContext:
        return context(
            *(task(i, (5, 17, 30, 45, 60, 90)[i % 6], kinds[i % 4]) for i in range(count))
        )

    base = mixed(50)
    critical = replace(
        base, profile=replace(base.profile, birth_utc=base.profile.birth_utc - timedelta(days=12))
    )
    future = tuple(FutureDay(DAY + timedelta(days=offset)) for offset in range(1, 8))
    return {
        "mixed_50": base,
        "mixed_100": mixed(100),
        "critical_50_with_horizon": replace(critical, future_days=future),
    }


def measure(operation: Callable[[], object], samples: int) -> dict[str, float]:
    for _ in range(3):
        operation()
    durations = []
    for _ in range(samples):
        start = perf_counter_ns()
        operation()
        durations.append((perf_counter_ns() - start) / 1_000_000)
    return {
        "min_ms": round(min(durations), 3),
        "median_ms": round(median(durations), 3),
        "p95_ms": round(sorted(durations)[ceil(0.95 * samples) - 1], 3),
        "max_ms": round(max(durations), 3),
    }


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
    results = {}
    for name, ctx in workloads().items():

        def run(selected: PlanContext = ctx) -> PlanResult:
            return build_schedule(selected)

        results[name] = measure(run, args.samples)
    print(
        json.dumps(
            {
                "algorithm_version": ALGORITHM_VERSION,
                "python": platform.python_version(),
                "platform": platform.system(),
                "samples": args.samples,
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
