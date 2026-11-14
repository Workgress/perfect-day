from app.db.base import Base
from app.modules.auth.models import AuthSession, EmailToken, RefreshToken
from app.modules.schedule.models import OnboardingCompletion, Schedule, ScheduleSlot
from app.modules.tasks.models import Task
from app.modules.users.models import User, UserProfile

__all__ = [
    "AuthSession",
    "Base",
    "EmailToken",
    "OnboardingCompletion",
    "RefreshToken",
    "Schedule",
    "ScheduleSlot",
    "Task",
    "User",
    "UserProfile",
    "metadata",
]

metadata = Base.metadata
