"""users and user_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "is_email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("birth_time", sa.Time(), nullable=True),
        sa.Column("birth_time_known", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("birth_tz", sa.Text(), nullable=True),
        sa.Column("birth_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chronotype", sa.Enum("lark", "dove", "owl", name="chronotype"), nullable=True),
        sa.Column(
            "chronotype_source",
            sa.Enum("manual", "quiz", name="chronotype_source"),
            nullable=True,
        ),
        sa.Column("timezone", sa.Text(), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column("wake_time", sa.Time(), server_default=sa.text("'07:00'"), nullable=False),
        sa.Column("sleep_time", sa.Time(), server_default=sa.text("'23:00'"), nullable=False),
        sa.Column("lunch_start", sa.Time(), server_default=sa.text("'12:00'"), nullable=False),
        sa.Column(
            "lunch_duration_min", sa.SmallInteger(), server_default=sa.text("60"), nullable=False
        ),
        sa.Column("work_start", sa.Time(), server_default=sa.text("'08:00'"), nullable=False),
        sa.Column("work_end", sa.Time(), server_default=sa.text("'18:00'"), nullable=False),
        sa.Column(
            "work_days",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{1,2,3,4,5}'"),
            nullable=False,
        ),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "birth_date IS NULL OR birth_date >= DATE '1900-01-01'",
            name="birth_date_range",
        ),
        sa.CheckConstraint("lunch_duration_min BETWEEN 0 AND 180", name="lunch_duration_range"),
        sa.CheckConstraint("work_end > work_start", name="work_window"),
        sa.CheckConstraint(
            "work_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name="work_days_range",
        ),
        sa.CheckConstraint(
            "onboarding_completed_at IS NULL OR ("
            "birth_date IS NOT NULL AND birth_at_utc IS NOT NULL AND chronotype IS NOT NULL)",
            name="onboarding_requires_birth_data",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS chronotype_source")
    op.execute("DROP TYPE IF EXISTS chronotype")
