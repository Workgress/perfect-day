from app.db.base import Base
from app.modules.schedule.models import Schedule, ScheduleSlot
from app.modules.tasks.models import Task
from app.modules.users.models import User, UserProfile

__all__ = ["Base", "Schedule", "ScheduleSlot", "Task", "User", "UserProfile", "metadata"]

metadata = Base.metadata
