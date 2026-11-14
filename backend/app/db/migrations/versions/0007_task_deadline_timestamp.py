from collections.abc import Sequence
from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    deadline_type = next(
        column["type"] for column in inspector.get_columns("tasks") if column["name"] == "deadline"
    )
    if not isinstance(deadline_type, sa.Date) and not (
        isinstance(deadline_type, sa.DateTime) and deadline_type.timezone
    ):
        raise RuntimeError("Unsupported tasks.deadline type; refusing to reinterpret existing data")
    if not inspector.has_table("onboarding_completions"):
        # A database stamped by the task branch skipped the canonical planner 0006.
        # Reuse that immutable migration so constraints/defaults match fresh installations.
        planner = import_module("app.db.migrations.versions.0006_planner_integration")
        planner.upgrade()
    if isinstance(deadline_type, sa.DateTime):
        return
    op.alter_column(
        "tasks",
        "deadline",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="deadline::timestamp AT TIME ZONE 'UTC'",
    )
    op.execute(
        """
        UPDATE tasks
        SET deadline = (
            ((deadline AT TIME ZONE 'UTC')::date + 1)::timestamp
            AT TIME ZONE COALESCE(
                (SELECT timezone FROM user_profiles WHERE user_id = tasks.user_id),
                'UTC'
            )
        ) - INTERVAL '1 microsecond'
        WHERE deadline IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tasks
        SET deadline = (
            deadline AT TIME ZONE COALESCE(
                (SELECT timezone FROM user_profiles WHERE user_id = tasks.user_id),
                'UTC'
            )
        )::date::timestamp AT TIME ZONE 'UTC'
        WHERE deadline IS NOT NULL
        """
    )
    op.alter_column(
        "tasks",
        "deadline",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        existing_nullable=True,
        postgresql_using="(deadline AT TIME ZONE 'UTC')::date",
    )
