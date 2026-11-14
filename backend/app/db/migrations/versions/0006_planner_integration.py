"""Persist successful onboarding operations and exact planner load factors."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "schedules", "load_factor", existing_type=sa.Numeric(3, 2), type_=sa.Numeric(4, 3)
    )
    op.create_table(
        "onboarding_completions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("request_body", postgresql.JSONB(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("onboarding_completions")
    op.alter_column(
        "schedules", "load_factor", existing_type=sa.Numeric(4, 3), type_=sa.Numeric(3, 2)
    )
