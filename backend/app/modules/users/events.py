from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ProfileChanged:
    user_id: UUID
    changed_fields: frozenset[str]
    occurred_at: datetime


class ProfileChangedHandler(Protocol):
    async def __call__(self, event: ProfileChanged) -> None: ...


async def profile_changed(event: ProfileChanged) -> None:
    """Post-commit extension point for the future scheduling module."""
