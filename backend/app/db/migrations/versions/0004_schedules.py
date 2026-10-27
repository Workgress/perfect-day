"""schedules and schedule_slots

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("algorithm_version", sa.String(20), nullable=False),
        sa.Column(
            "trigger",
            sa.Enum(
                "initial",
                "task_created",
                "task_updated",
                "task_deleted",
                "status_changed",
                "manual_edit",
                "profile_changed",
                "nightly",
                name="schedule_trigger",
            ),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("critical_level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("load_factor", sa.Numeric(3, 2), server_default=sa.text("1.00"), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("critical_level BETWEEN 0 AND 3", name="critical_level_range"),
        sa.CheckConstraint("load_factor > 0 AND load_factor <= 1", name="load_factor_range"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "date", "version"),
    )
    op.create_index(
        "uq_schedules_active_per_day",
        "schedules",
        ["user_id", "date"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "schedule_slots",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("task", "break", "lunch", "rest", name="slot_kind"),
            nullable=False,
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "reason_codes",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.CheckConstraint("end_at > start_at", name="interval"),
        sa.CheckConstraint(
            "kind = 'task' OR task_id IS NULL", name="only_task_slots_reference_tasks"
        ),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedule_slots_schedule_id_start_at",
        "schedule_slots",
        ["schedule_id", "start_at"],
    )
    op.create_index("ix_schedule_slots_task_id", "schedule_slots", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_schedule_slots_task_id", table_name="schedule_slots")
    op.drop_index("ix_schedule_slots_schedule_id_start_at", table_name="schedule_slots")
    op.drop_table("schedule_slots")
    op.drop_index("uq_schedules_active_per_day", table_name="schedules")
    op.drop_table("schedules")
    op.execute("DROP TYPE IF EXISTS slot_kind")
    op.execute("DROP TYPE IF EXISTS schedule_trigger")
