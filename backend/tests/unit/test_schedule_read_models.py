from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.schedule.read_models import ScheduleReadSlot
from scripts.generate_schedule_read_schema import SCHEMA_PATH, content


def slot(**changes: object) -> ScheduleReadSlot:
    return ScheduleReadSlot.model_validate(
        {
            "id": UUID(int=1),
            "kind": "task",
            "task_id": UUID(int=2),
            "start_at": "2026-10-25T02:30:00+02:00",
            "end_at": "2026-10-25T02:30:00+01:00",
            "is_pinned": False,
            "reason_codes": [],
            "explanation": None,
            **changes,
        }
    )


def test_slot_serialization_preserves_dst_fold_as_distinct_utc_instants() -> None:
    value = slot()
    assert value.start_at == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert value.end_at == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    payload = value.model_dump(mode="json")
    assert payload["start_at"] == "2026-10-25T00:30:00Z"
    assert payload["end_at"] == "2026-10-25T01:30:00Z"


@pytest.mark.parametrize(
    "changes",
    [
        {"start_at": "2026-10-25T00:30:00"},
        {"end_at": "2026-10-25T00:30:00Z"},
        {"task_id": None},
        {"kind": "break"},
        {"score": 0.5},
        {"preservation": "past"},
    ],
)
def test_slot_rejects_invalid_boundaries_identity_and_internal_fields(changes: dict) -> None:
    with pytest.raises(ValidationError):
        slot(**changes)


def test_read_slot_is_immutable() -> None:
    value = slot()
    with pytest.raises(ValidationError):
        value.is_pinned = True


def test_handoff_schema_matches_the_serialized_read_model() -> None:
    assert SCHEMA_PATH.read_bytes() == content()
