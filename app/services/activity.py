"""Activity log helper. Does NOT commit; it joins the caller's transaction."""
from sqlalchemy.orm import Session

from app.models import ActivityLog, User


def log_activity(
    db: Session, user: User | None, action: str, *, project_id: int | None = None,
    task_id: int | None = None, details: dict | None = None,
) -> None:
    """Add an audit event to the current transaction without committing it."""
    db.add(ActivityLog(user_id=user.id if user else None, action=action,
                       project_id=project_id, task_id=task_id, details=details))
