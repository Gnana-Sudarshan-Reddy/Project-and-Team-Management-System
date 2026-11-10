"""Import and re-export every ORM model so SQLAlchemy registers its tables."""

from app.models.activity import ActivityLog
from app.models.comment import TaskComment
from app.models.project import Project, ProjectMember
from app.models.task import Task
from app.models.user import Role, User

__all__ = ["ActivityLog", "TaskComment", "Project", "ProjectMember", "Task", "Role", "User"]
