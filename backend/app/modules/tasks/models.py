import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPkMixin, pg_enum


class TaskType(enum.StrEnum):
    INTELLECTUAL = "intellectual"
    PHYSICAL = "physical"
    CREATIVE = "creative"
    ROUTINE = "routine"


class TaskPriority(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    DONE = "done"
    SKIPPED = "skipped"


class Task(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("duration_min BETWEEN 5 AND 480", name="duration_range"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("NOT is_pinned OR pinned_start IS NOT NULL", name="pinned_requires_start"),
        CheckConstraint(
            "status <> 'done' OR completed_at IS NOT NULL",
            name="done_requires_completed_at",
        ),
        CheckConstraint(
            "actual_start IS NULL OR actual_end IS NULL OR actual_end > actual_start",
            name="actual_interval",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "ix_tasks_user_id_planned_date",
            "user_id",
            "planned_date",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_tasks_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None]
    type: Mapped[TaskType] = mapped_column(pg_enum(TaskType, "task_type"))
    priority: Mapped[TaskPriority] = mapped_column(
        pg_enum(TaskPriority, "task_priority"),
        default=TaskPriority.MEDIUM,
        server_default=text("'medium'"),
    )
    duration_min: Mapped[int]
    planned_date: Mapped[date]
    preferred_start: Mapped[time | None]
    deadline: Mapped[datetime | None]
    is_pinned: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    pinned_start: Mapped[datetime | None]
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, "task_status"),
        default=TaskStatus.PENDING,
        server_default=text("'pending'"),
    )
    completed_at: Mapped[datetime | None]
    actual_start: Mapped[datetime | None]
    actual_end: Mapped[datetime | None]
    moved_from_date: Mapped[date | None]
    recurrence_rule_id: Mapped[uuid.UUID | None]
    parent_task_id: Mapped[uuid.UUID | None]
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    deleted_at: Mapped[datetime | None]
