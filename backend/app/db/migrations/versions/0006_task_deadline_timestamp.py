from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
