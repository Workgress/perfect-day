import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPkMixin, pg_enum


class ScheduleTrigger(enum.StrEnum):
    INITIAL = "initial"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_DELETED = "task_deleted"
    STATUS_CHANGED = "status_changed"
    MANUAL_EDIT = "manual_edit"
    PROFILE_CHANGED = "profile_changed"
    NIGHTLY = "nightly"


class SlotKind(enum.StrEnum):
    TASK = "task"
    BREAK = "break"
    LUNCH = "lunch"
    REST = "rest"


class Schedule(UUIDPkMixin, Base):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "date", "version"),
        Index(
            "uq_schedules_active_per_day",
            "user_id",
            "date",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("critical_level BETWEEN 0 AND 3", name="critical_level_range"),
        CheckConstraint("load_factor > 0 AND load_factor <= 1", name="load_factor_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[dt.date]
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    algorithm_version: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[ScheduleTrigger] = mapped_column(pg_enum(ScheduleTrigger, "schedule_trigger"))
    generated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    critical_level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    load_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        default=Decimal("1.00"),
        server_default=text("1.00"),
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    slots: Mapped[list["ScheduleSlot"]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScheduleSlot.start_at",
    )


class ScheduleSlot(UUIDPkMixin, Base):
    __tablename__ = "schedule_slots"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="interval"),
        CheckConstraint("kind = 'task' OR task_id IS NULL", name="only_task_slots_reference_tasks"),
        Index("ix_schedule_slots_schedule_id_start_at", "schedule_id", "start_at"),
        Index("ix_schedule_slots_task_id", "task_id"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    kind: Mapped[SlotKind] = mapped_column(pg_enum(SlotKind, "slot_kind"))
    start_at: Mapped[dt.datetime]
    end_at: Mapped[dt.datetime]
    is_pinned: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=text("'{}'::text[]"),
    )
    explanation: Mapped[str | None]

    schedule: Mapped[Schedule] = relationship(back_populates="slots")


class OnboardingCompletion(Base):
    """Permanent successful operation receipt, scoped to its authenticated owner."""

    __tablename__ = "onboarding_completions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
