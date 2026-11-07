from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="expiration"),
        sa.CheckConstraint("last_used_at >= created_at", name="last_used"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
        sa.CheckConstraint("expires_at > created_at", name="expiration"),
        sa.CheckConstraint("used_at IS NULL OR used_at >= created_at", name="usage"),
        sa.CheckConstraint(
            "replaced_by_id IS NULL OR (used_at IS NOT NULL AND replaced_by_id <> id)",
            name="replacement",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("replaced_by_id"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index(
        "uq_refresh_tokens_active_per_session",
        "refresh_tokens",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )

    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("verify_email", "reset_password", name="email_token_purpose"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
        sa.CheckConstraint("expires_at > created_at", name="expiration"),
        sa.CheckConstraint("used_at IS NULL OR used_at >= created_at", name="usage"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_email_tokens_user_id_purpose", "email_tokens", ["user_id", "purpose"])
    op.create_index("ix_email_tokens_expires_at", "email_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_table("email_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("sessions")
    op.execute("DROP TYPE email_token_purpose")
