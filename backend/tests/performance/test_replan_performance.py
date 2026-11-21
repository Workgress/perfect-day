import json
import platform
import sys
from datetime import UTC, datetime, timedelta
from time import perf_counter_ns

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.schedule.models import Schedule, ScheduleTrigger
from app.modules.schedule.planning_schemas import ScheduleReplanResponse
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task
from app.modules.users.dependencies import get_clock
from app.modules.users.models import User, UserProfile
from scripts.benchmark_planner import timing_summary
from tests.db.factories import make_task
from tests.integration.test_schedule_read_api import DAY
from tests.integration.test_schedule_read_api import alembic_config as alembic_config
from tests.integration.test_schedule_read_api import auth_api as auth_api
from tests.integration.test_schedule_read_api import engine as engine
from tests.integration.test_schedule_read_api import migrated_url as migrated_url
from tests.integration.test_schedule_read_api import schedule_api as schedule_api
from tests.integration.test_schedule_read_api import tasks_api as tasks_api
from tests.integration.test_tasks_api import TasksAPI

pytestmark = [pytest.mark.docker, pytest.mark.performance]
SAMPLES = 20
WARMUPS = 3
P95_BUDGET_MS = 2000


async def stable_state(api: TasksAPI) -> tuple:
    async with api.auth.engine.connect() as connection:
        tasks = (
            await connection.execute(
                select(
                    Task.id,
                    Task.version,
                    Task.planned_date,
                    Task.status,
                    Task.actual_start,
                    Task.is_pinned,
                )
                .where(Task.user_id == api.user_id)
                .order_by(Task.id)
            )
        ).all()
        targets = (
            await connection.execute(
                select(Schedule.date, Schedule.id, Schedule.version)
                .where(
                    Schedule.user_id == api.user_id,
                    Schedule.is_active.is_(True),
                    Schedule.date > DAY,
                )
                .order_by(Schedule.date)
            )
        ).all()
        return tasks, targets


@pytest.mark.parametrize(("count", "critical"), [(50, False), (100, False), (50, True)])
async def test_replan_with_protected_intervals_and_occupied_horizon(
    schedule_api: TasksAPI,
    pytestconfig: pytest.Config,
    count: int,
    critical: bool,
) -> None:
    if (
        pytestconfig.getoption("cov_source", default=[])
        or sys.gettrace() is not None
        or sys.getprofile() is not None
    ):
        pytest.skip("Measure separately without coverage, profiling or a debugger")
    api = schedule_api
    now = datetime(DAY.year, DAY.month, DAY.day, 8, 30, tzinfo=UTC)
    clock = FrozenClock(now)
    api.auth.app.dependency_overrides[get_clock] = lambda: clock
    async with AsyncSession(api.auth.engine, expire_on_commit=False) as session, session.begin():
        user = await session.get(User, api.user_id)
        profile = await session.get(UserProfile, api.user_id)
        assert user is not None and profile is not None
        profile.work_days = list(range(1, 8))
        if critical:
            profile.birth_date = DAY - timedelta(days=14)
            profile.birth_at_utc = datetime(
                profile.birth_date.year,
                profile.birth_date.month,
                profile.birth_date.day,
                7,
                tzinfo=UTC,
            )
        protected_rows = []
        for index in range(count):
            pinned_start = now.replace(hour=9 + index, minute=0) if index < 2 else None
            row = await make_task(
                session,
                user,
                planned_date=DAY,
                type="routine"
                if index < 2
                else ("intellectual", "physical", "creative", "routine")[index % 4],
                duration_min=30 if index < 2 else (5, 17, 30, 45, 60, 90)[index % 6],
                is_pinned=index < 2,
                pinned_start=pinned_start,
            )
            if index < 2:
                protected_rows.append(row)
        for offset in range(1, 8):
            day = DAY + timedelta(days=offset)
            await make_task(
                session,
                user,
                planned_date=day,
                type="routine",
                duration_min=30,
                is_pinned=True,
                pinned_start=datetime(day.year, day.month, day.day, 5, tzinfo=UTC),
            )
        scheduler = ScheduleService(session, clock)
        for offset in range(1, 8):
            await scheduler.replan(
                api.user_id, DAY + timedelta(days=offset), ScheduleTrigger.INITIAL
            )
        initial = await scheduler.replan(api.user_id, DAY, ScheduleTrigger.INITIAL)
        protected = {row.id for row in protected_rows}
        intervals = {
            slot.task.task_id: slot.interval
            for slot in initial.plan.slots
            if slot.task is not None and slot.task.task_id in protected
        }
        protected_rows[0].is_pinned = False
        protected_rows[0].pinned_start = None
        protected_rows[0].actual_start = now - timedelta(minutes=15)
        first_version = (await scheduler.repository.active(api.user_id, (DAY,)))[DAY].version
    body = {"planned_date": DAY.isoformat()}
    headers = {"Authorization": f"Bearer {api.token}"}
    durations = []
    baseline = None
    for index in range(WARMUPS + SAMPLES):
        start = perf_counter_ns()
        response = await api.auth.client.post("/api/v1/schedule/replan", json=body, headers=headers)
        elapsed = (perf_counter_ns() - start) / 1_000_000
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = ScheduleReplanResponse.model_validate(response.json())
        assert result.schedule.version == first_version + index + 1
        assert not result.schedule.moves
        assert len(result.placement_explanations) + len(result.unscheduled_explanations) == count
        placed = {item.task_id: item for item in result.placement_explanations}
        for task_id, interval in intervals.items():
            assert (placed[task_id].start_at, placed[task_id].end_at) == (
                interval.start,
                interval.end,
            )
        assert placed[protected_rows[0].id].preservation == "started"
        assert placed[protected_rows[1].id].preservation == "pinned"
        if index == WARMUPS - 1:
            baseline = await stable_state(api)
        if index >= WARMUPS:
            durations.append(elapsed)
    assert await stable_state(api) == baseline
    summary = timing_summary(durations)
    print(
        json.dumps(
            {
                "scenario": "http_replan_critical" if critical else "http_replan_mixed",
                "transport": "in-process ASGI; Docker PostgreSQL and Redis; no proxy or TLS",
                "algorithm_version": ALGORITHM_VERSION,
                "python": platform.python_version(),
                "platform": platform.system(),
                "tasks": count,
                "horizon_days": 7,
                "future_tasks": 7,
                "protected_intervals": 2,
                "samples": SAMPLES,
                "warmups": WARMUPS,
                "p95_budget_ms": P95_BUDGET_MS,
                **summary,
            }
        )
    )
    assert summary["p95_ms"] < P95_BUDGET_MS
