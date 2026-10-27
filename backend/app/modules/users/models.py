import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin, pg_enum


class Chronotype(enum.StrEnum):
    LARK = "lark"
    DOVE = "dove"
    OWL = "owl"


class ChronotypeSource(enum.StrEnum):
    MANUAL = "manual"
    QUIZ = "quiz"


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str]
    is_email_verified: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None]

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "birth_date IS NULL OR birth_date >= DATE '1900-01-01'",
            name="birth_date_range",
        ),
        CheckConstraint("lunch_duration_min BETWEEN 0 AND 180", name="lunch_duration_range"),
        CheckConstraint("work_end > work_start", name="work_window"),
        CheckConstraint(
            "work_days <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]",
            name="work_days_range",
        ),
        CheckConstraint(
            "onboarding_completed_at IS NULL OR ("
            "birth_date IS NOT NULL AND birth_at_utc IS NOT NULL AND chronotype IS NOT NULL)",
            name="onboarding_requires_birth_data",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(100))
    birth_date: Mapped[date | None]
    birth_time: Mapped[time | None]
    birth_time_known: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    birth_tz: Mapped[str | None]
    birth_at_utc: Mapped[datetime | None]
    chronotype: Mapped[Chronotype | None] = mapped_column(pg_enum(Chronotype, "chronotype"))
    chronotype_source: Mapped[ChronotypeSource | None] = mapped_column(
        pg_enum(ChronotypeSource, "chronotype_source")
    )
    timezone: Mapped[str] = mapped_column(default="UTC", server_default=text("'UTC'"))
    wake_time: Mapped[time] = mapped_column(default=time(7, 0), server_default=text("'07:00'"))
    sleep_time: Mapped[time] = mapped_column(default=time(23, 0), server_default=text("'23:00'"))
    lunch_start: Mapped[time] = mapped_column(default=time(12, 0), server_default=text("'12:00'"))
    lunch_duration_min: Mapped[int] = mapped_column(
        SmallInteger, default=60, server_default=text("60")
    )
    work_start: Mapped[time] = mapped_column(default=time(8, 0), server_default=text("'08:00'"))
    work_end: Mapped[time] = mapped_column(default=time(18, 0), server_default=text("'18:00'"))
    work_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        default=lambda: [1, 2, 3, 4, 5],
        server_default=text("'{1,2,3,4,5}'"),
    )
    onboarding_completed_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="profile")
