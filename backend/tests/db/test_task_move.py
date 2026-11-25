import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import AppError
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.repository import ScheduleRepository
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.models import Task
from app.modules.tasks.placement_schemas import TaskMoveRequest
from app.modules.tasks.placement_service import TaskPlacementService
from app.modules.users.models import User
from tests.db.factories import make_task
from tests.db.test_schedule_service import CLOCK, DAY
from tests.db.test_task_pin import at, command, seed
from tests.db.test_task_schedule_updates import committed_owner as committed_owner
from tests.db.test_task_schedule_updates import snapshot

pytestmark = pytest.mark.docker


async def test_move_forward_and_back_preserves_date_lock_and_updates_both_days(
    session: AsyncSession,
) -> None:
    owner, task, placement, events = await seed(session)
    earlier, later = DAY + timedelta(days=1), DAY + timedelta(days=2)
    async with session.begin():
        row = await session.get(Task, task.id)
        row.is_date_locked = True
    forward = TaskMoveRequest.model_validate(
        command(task, day=later, versions={DAY: 1, later: 0}).model_dump()
    )
    moved = await placement.move(owner, task.id, forward)
    assert moved.planned_date == later and moved.is_pinned and moved.is_date_locked
    backward = TaskMoveRequest.model_validate(
        command(moved, day=earlier, versions={later: 1, earlier: 0}).model_dump()
    )
    returned = await placement.move(owner, task.id, backward)
    assert returned.planned_date == earlier and returned.pinned_start == at(9, 7, day=earlier)
    assert returned.is_date_locked and len(events) == 2
    async with session.begin():
        plans = await placement.scheduler.repository.active(owner, (DAY, earlier, later))
        assert {day: plan.version for day, plan in plans.items()} == {DAY: 2, earlier: 1, later: 2}
        assert not any(slot.task_id == task.id for day in (DAY, later) for slot in plans[day].slots)
        assert any(slot.task_id == task.id and slot.is_pinned for slot in plans[earlier].slots)
        stored = await session.get(Task, task.id)
        assert stored.moved_from_date is None
    before = await snapshot(session)
    repeat = TaskMoveRequest.model_validate(
        command(returned, day=earlier, versions={earlier: 1}).model_dump()
    )
    assert await placement.move(owner, task.id, repeat) == returned
    assert await snapshot(session) == before and len(events) == 2


async def test_opposite_moves_share_locks_and_reject_stale_day_versions(
    engine: AsyncEngine, committed_owner: UUID
) -> None:
    earlier, later = DAY + timedelta(days=1), DAY + timedelta(days=2)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = await session.get(User, committed_owner)
        first = await make_task(
            session, user, planned_date=earlier, type="routine", duration_min=30
        )
        second = await make_task(session, user, planned_date=later, type="routine", duration_min=30)
        scheduler = ScheduleService(session, CLOCK)
        for day in (earlier, later):
            await scheduler.replan(committed_owner, day, ScheduleTrigger.INITIAL)
        requests = [
            (
                item.id,
                TaskMoveRequest(
                    planned_date=target,
                    start_at=at(hour, 7, day=target),
                    version=item.version,
                    schedule_versions={earlier: 1, later: 1},
                ),
            )
            for item, target, hour in ((first, later, 9), (second, earlier, 10))
        ]
        await session.commit()

    async def move(task_id, request):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await TaskPlacementService(session, CLOCK, ScheduleService(session, CLOCK)).move(
                committed_owner, task_id, request
            )

    results = await asyncio.wait_for(
        asyncio.gather(*(move(*request) for request in requests), return_exceptions=True),
        timeout=15,
    )
    errors = [result for result in results if isinstance(result, AppError)]
    assert len(errors) == 1 and errors[0].body.code == "SCHEDULE_VERSION_CONFLICT"
    assert len([result for result in results if not isinstance(result, BaseException)]) == 1
    async with AsyncSession(engine) as session:
        plans = await ScheduleRepository(session).active(committed_owner, (earlier, later))
        assert {day: plan.version for day, plan in plans.items()} == {earlier: 2, later: 2}
        slots = [slot for plan in plans.values() for slot in plan.slots if slot.task_id is not None]
        assert len(slots) == 2 and len({slot.task_id for slot in slots}) == 2
        assert sum(slot.is_pinned for slot in slots) == 1
