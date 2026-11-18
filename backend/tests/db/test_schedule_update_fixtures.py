import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import FrozenClock
from app.modules.planner.config import ALGORITHM_VERSION
from app.modules.schedule.models import ScheduleTrigger
from app.modules.schedule.reader import ScheduleReader
from app.modules.schedule.service import ScheduleService
from app.modules.tasks.schemas import TaskCreate, TaskPatch
from app.modules.tasks.service import TaskService
from app.modules.users.models import UserProfile
from tests.db.factories import make_task
from tests.db.test_schedule_service import setup_user

FIXTURE = Path(__file__).resolve().parents[3] / "contracts/fixtures/schedule_update_cases.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
pytestmark = pytest.mark.docker


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda case: case["id"])
async def test_task_change_core_storage_reader_fixture(
    session: AsyncSession, case: dict[str, Any]
) -> None:
    assert DATA["schema_version"] == 1 and DATA["algorithm_version"] == ALGORITHM_VERSION
    defaults = DATA["defaults"]
    day = date.fromisoformat(case.get("day", defaults["day"]))
    clock = FrozenClock(datetime.fromisoformat(case.get("now", defaults["now"])))
    profile_values = defaults["profile"] | case.get("profile", {})
    user = await setup_user(session, completed=True)
    user_id = user.id
    profile = await session.get(UserProfile, user_id)
    assert profile is not None
    profile.birth_date = day - timedelta(days=profile_values.pop("birth_days_ago"))
    profile.birth_time = time(12)
    profile.birth_tz = profile_values["timezone"]
    profile.work_days = list(range(1, 8))
    for field, value in profile_values.items():
        setattr(
            profile,
            field,
            time.fromisoformat(value) if field in {"work_start", "work_end"} else value,
        )
    scheduler = ScheduleService(session, clock)
    aliases: dict[str, UUID] = {}
    for seed in case.get("seed_tasks", []):
        fields = dict(seed["body"])
        if "pinned_start" in fields:
            fields["pinned_start"] = datetime.fromisoformat(fields["pinned_start"])
        task = await make_task(session, user, planned_date=day, title=seed["task"], **fields)
        aliases[seed["task"]] = task.id
    if aliases:
        await scheduler.replan(user_id, day, ScheduleTrigger.INITIAL)
    await session.commit()
    tasks = TaskService(session, clock, coordinator=scheduler)
    reader = ScheduleReader(session)

    async def read() -> dict:
        async with session.begin():
            days = await scheduler.repository.active_dates(user_id, day)
            return {selected.isoformat(): await reader.get(user_id, selected) for selected in days}

    def placements(documents: dict) -> dict:
        return {
            slot.task_id: slot
            for document in documents.values()
            for slot in document.slots
            if slot.task_id
        }

    for action in case["actions"]:
        before = await read()
        before_slots = placements(before)
        alias, operation = action["task"], action["operation"]
        if operation == "create":
            body = TaskCreate.model_validate(
                {"title": alias, "planned_date": day, **action["body"]}
            )
            created = await tasks.create(user_id, body)
            aliases[alias] = created.id
        elif operation == "advance_to_started":
            clock = FrozenClock(before_slots[aliases[alias]].start_at + timedelta(minutes=1))
            tasks.clock = scheduler.clock = clock
        else:
            current = await tasks.get(user_id, aliases[alias])
            if operation == "patch":
                await tasks.patch(
                    user_id,
                    current.id,
                    TaskPatch.model_validate({"version": current.version, **action["body"]}),
                )
            else:
                command = {
                    "delete": tasks.delete,
                    "complete": tasks.complete,
                    "skip": tasks.skip,
                    "reopen": tasks.reopen,
                }[operation]
                await command(user_id, current.id, current.version)
        after = await read()
        saved = placements(after)
        expected = action["expected"]
        for name, status in expected.get("statuses", {}).items():
            assert (await tasks.get(user_id, aliases[name])).status == status
        for name, planned in expected.get("dates", {}).items():
            assert (await tasks.get(user_id, aliases[name])).planned_date.isoformat() == planned
        if expected.get("no_replan"):
            assert after == before
        for name in expected.get("preserved", []):
            old, new = before_slots[aliases[name]], saved[aliases[name]]
            assert (old.start_at, old.end_at, old.is_pinned) == (
                new.start_at,
                new.end_at,
                new.is_pinned,
            )
        for name in expected.get("absent", []):
            assert aliases[name] not in saved
        if "unscheduled" in expected:
            items = [item for document in after.values() for item in document.unscheduled]
            assert {item.task_id for item in items} == {
                aliases[name] for name in expected["unscheduled"]
            }
            assert all(item.reason_codes for item in items)
        if "schedule_dates" in expected:
            assert set(after) == set(expected["schedule_dates"])
        for kind in expected.get("slot_kinds", []):
            assert any(slot.kind == kind for document in after.values() for slot in document.slots)
        for name in expected.get("moved", []):
            assert any(
                move.task_id == aliases[name] and move.to_date > day
                for document in after.values()
                for move in document.moves
            )
        for name in expected.get("within_deadline", []):
            current = await tasks.get(user_id, aliases[name])
            assert current.deadline is not None and saved[current.id].end_at <= current.deadline
        for name in expected.get("not_before_now", []):
            assert saved[aliases[name]].start_at >= clock.now()
        if "critical_level" in expected:
            assert after[day.isoformat()].metrics.critical_level == expected["critical_level"]
        for document in after.values():
            assert document.algorithm_version == ALGORITHM_VERSION
            assert document.timezone == profile_values["timezone"]
            assert document.version >= 1
            for left, right in zip(document.slots, document.slots[1:], strict=False):
                assert left.end_at <= right.start_at
            assert type(document).model_validate_json(document.model_dump_json()) == document
