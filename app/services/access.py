"""Shared lookups + access-control rules for users, projects and tasks."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.permissions import RoleName
from app.models import Project, ProjectMember, Task, User


def has_permission(user: User, perm: str) -> bool:
    """Return whether the user's role grants the requested permission."""
    return perm in (user.role.permissions or [])


def is_admin(user: User) -> bool:
    """Return whether the user has the built-in administrator role."""
    return user.role.name == RoleName.ADMIN


def accessible_project_ids(user: User):
    """Subquery of project ids the user owns or is a member of."""
    member_of = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    return select(Project.id).where(or_(Project.owner_id == user.id, Project.id.in_(member_of)))


def get_project_or_404(db: Session, project_id: int) -> Project:
    """Load a project by ID or raise the API's standard not-found error."""
    project = db.get(Project, project_id)
    if not project:
        raise NotFoundError("Project not found")
    return project


def ensure_project_access(db: Session, user: User, project_id: int) -> Project:
    """Return a project only when the user is an admin, owner, or member."""
    project = get_project_or_404(db, project_id)
    if is_admin(user) or project.owner_id == user.id or any(m.user_id == user.id for m in project.members):
        return project
    raise ForbiddenError("You do not have access to this project")


def ensure_project_owner(project: Project, user: User) -> None:
    """Require the user to own the project unless they are an administrator."""
    if not (is_admin(user) or project.owner_id == user.id):
        raise ForbiddenError("Only the project owner or an admin can do this")


def get_task_or_404(db: Session, task_id: int) -> Task:
    """Load a task by ID or raise the API's standard not-found error."""
    task = db.get(Task, task_id)
    if not task:
        raise NotFoundError("Task not found")
    return task


def get_user_or_404(db: Session, user_id: int) -> User:
    """Load a user by ID or raise the API's standard not-found error."""
    user = db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    return user
