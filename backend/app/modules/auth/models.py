import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPkMixin, pg_enum


class EmailTokenPurpose(enum.StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class AuthSession(UUIDPkMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiration"),
        CheckConstraint("last_used_at >= created_at", name="last_used"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_used_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]
    ip: Mapped[str | None]
    user_agent: Mapped[str | None]


class RefreshToken(UUIDPkMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
        CheckConstraint("expires_at > created_at", name="expiration"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="usage"),
        CheckConstraint(
            "replaced_by_id IS NULL OR (used_at IS NOT NULL AND replaced_by_id <> id)",
            name="replacement",
        ),
        Index(
            "uq_refresh_tokens_active_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("used_at IS NULL"),
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None]
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), unique=True
    )


class EmailToken(UUIDPkMixin, Base):
    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
        CheckConstraint("expires_at > created_at", name="expiration"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="usage"),
        Index("ix_email_tokens_user_id_purpose", "user_id", "purpose"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[EmailTokenPurpose] = mapped_column(
        pg_enum(EmailTokenPurpose, "email_token_purpose")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None]
