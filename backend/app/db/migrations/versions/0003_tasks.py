"""tasks

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "type",
            sa.Enum("intellectual", "physical", "creative", "routine", name="task_type"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("high", "medium", "low", name="task_priority"),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False),
        sa.Column("preferred_start", sa.Time(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("pinned_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "scheduled", "done", "skipped", name="task_status"),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moved_from_date", sa.Date(), nullable=True),
        sa.Column("recurrence_rule_id", sa.Uuid(), nullable=True),
        sa.Column("parent_task_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("duration_min BETWEEN 5 AND 480", name="duration_range"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        sa.CheckConstraint(
            "NOT is_pinned OR pinned_start IS NOT NULL", name="pinned_requires_start"
        ),
        sa.CheckConstraint(
            "status <> 'done' OR completed_at IS NOT NULL",
            name="done_requires_completed_at",
        ),
        sa.CheckConstraint(
            "actual_start IS NULL OR actual_end IS NULL OR actual_end > actual_start",
            name="actual_interval",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tasks_user_id_planned_date",
        "tasks",
        ["user_id", "planned_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_tasks_user_id_updated_at", "tasks", ["user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_user_id_updated_at", table_name="tasks")
    op.drop_index("ix_tasks_user_id_planned_date", table_name="tasks")
    op.drop_table("tasks")
    op.execute("DROP TYPE IF EXISTS task_status")
    op.execute("DROP TYPE IF EXISTS task_priority")
    op.execute("DROP TYPE IF EXISTS task_type")
