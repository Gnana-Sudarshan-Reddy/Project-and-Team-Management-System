"""Endpoints for task workflows, comments, filtering, and task history."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.exceptions import AppError, ForbiddenError
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import ActivityLog, Project, Task, TaskComment, User
from app.models.enums import TaskPriority, TaskStatus
from app.models.mixins import utcnow
from app.schemas.common import Page, PaginationParams, make_page
from app.schemas.task import ActivityOut, CommentCreate, CommentOut, TaskCreate, TaskOut, TaskUpdate
from app.services.access import (
    accessible_project_ids, ensure_project_access, get_task_or_404, get_user_or_404, has_permission, is_admin,
)
from app.services.activity import log_activity
from app.services.utils import apply_changes, plain

router = APIRouter(prefix="/tasks", tags=["Tasks"])

SORTABLE_TASK_COLUMNS = {
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
    "due_date": Task.due_date,
    "title": Task.title,
}


# ---------- validation helpers ----------
def validate_deadline(project: Project, due: date | None) -> None:
    """Ensure a task deadline is not in the past or beyond the project end date."""
    if due is None:
        return
    if due < date.today():
        raise AppError("due_date cannot be in the past", 422, "invalid_deadline")
    if project.end_date and due > project.end_date:
        raise AppError(f"due_date cannot be after the project end date ({project.end_date})", 422, "invalid_deadline")


def validate_assignee(db: Session, project: Project, assignee_id: int | None) -> None:
    """Ensure an assignee exists, is active, and belongs to the project."""
    if assignee_id is None:
        return
    user = get_user_or_404(db, assignee_id)
    if not user.is_active:
        raise AppError("Cannot assign tasks to a deactivated user", 422, "inactive_user")
    if user.id != project.owner_id and not any(m.user_id == user.id for m in project.members):
        raise AppError("Assignee must be a member of the project", 422, "assignee_not_member")


class TaskFilters:
    """Validated query parameters shared by task list endpoints."""

    project_id: int | None
    status_: TaskStatus | None
    priority: TaskPriority | None
    assignee_id: int | None
    created_by_id: int | None
    q: str | None
    due_before: date | None
    due_after: date | None
    overdue: bool | None
    sort_by: str
    order: str

    def __init__(
        self,
        project_id: int | None = None,
        status_: TaskStatus | None = Query(None, alias="status"),
        priority: TaskPriority | None = None,
        assignee_id: int | None = None,
        created_by_id: int | None = None,
        q: str | None = Query(None, description="Search title/description"),
        due_before: date | None = None,
        due_after: date | None = None,
        overdue: bool | None = Query(None, description="true = only overdue, false = only not overdue"),
        sort_by: str = Query("created_at", pattern="^(created_at|updated_at|due_date|title)$"),
        order: str = Query("desc", pattern="^(asc|desc)$"),
    ):
        """Store validated query values for the shared task-list query."""
        self.project_id = project_id
        self.status_ = status_
        self.priority = priority
        self.assignee_id = assignee_id
        self.created_by_id = created_by_id
        self.q = q
        self.due_before = due_before
        self.due_after = due_after
        self.overdue = overdue
        self.sort_by = sort_by
        self.order = order


def _list_tasks(
    db: Session,
    user: User,
    filters: TaskFilters,
    params: PaginationParams,
    force_assignee_id: int | None = None,
):
    """Build and execute the shared filtered, sorted, paginated task query."""
    stmt = select(Task)
    if not is_admin(user):
        stmt = stmt.where(Task.project_id.in_(accessible_project_ids(user)))
    if force_assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == force_assignee_id)
    elif filters.assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == filters.assignee_id)
    if filters.project_id is not None:
        stmt = stmt.where(Task.project_id == filters.project_id)
    if filters.status_ is not None:
        stmt = stmt.where(Task.status == filters.status_.value)
    if filters.priority is not None:
        stmt = stmt.where(Task.priority == filters.priority.value)
    if filters.created_by_id is not None:
        stmt = stmt.where(Task.created_by_id == filters.created_by_id)
    if filters.q:
        like = f"%{filters.q}%"
        stmt = stmt.where(or_(Task.title.ilike(like), Task.description.ilike(like)))
    if filters.due_before is not None:
        stmt = stmt.where(Task.due_date <= filters.due_before)
    if filters.due_after is not None:
        stmt = stmt.where(Task.due_date >= filters.due_after)
    if filters.overdue is not None:
        overdue_condition = (
            (Task.due_date < date.today())
            & (Task.status != TaskStatus.DONE.value)
        )
        if filters.overdue:
            stmt = stmt.where(overdue_condition)
        else:
            stmt = stmt.where(
                or_(
                    Task.due_date.is_(None),
                    Task.due_date >= date.today(),
                    Task.status == TaskStatus.DONE.value,
                )
            )
    sort_column = SORTABLE_TASK_COLUMNS[filters.sort_by]
    ordering = sort_column.asc() if filters.order == "asc" else sort_column.desc()
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ordering, Task.id.desc()).offset(params.offset).limit(params.size)).all()
    return make_page(TaskOut, rows, total, params)


def _load_accessible_task(db: Session, user: User, task_id: int) -> tuple[Task, Project]:
    """Load a task and its project after enforcing project-level access."""
    task = get_task_or_404(db, task_id)
    return task, ensure_project_access(db, user, task.project_id)


# ---------- CRUD ----------
@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                user: User = Depends(require_permission(Perm.TASKS_CREATE))):
    """Create a task in an accessible project and record its creation."""
    project = ensure_project_access(db, user, payload.project_id)
    validate_deadline(project, payload.due_date)
    validate_assignee(db, project, payload.assignee_id)
    data = payload.model_dump()
    data["status"], data["priority"] = plain(data["status"]), plain(data["priority"])
    task = Task(**data, created_by_id=user.id, updated_by_id=user.id)
    if task.status == TaskStatus.DONE.value:
        task.completed_at = utcnow()
    db.add(task)
    db.flush()
    log_activity(db, user, "task.created", project_id=project.id, task_id=task.id,
                 details={"title": task.title, "assignee_id": task.assignee_id})
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=Page[TaskOut])
def list_tasks(
    filters: TaskFilters = Depends(),
    params: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List accessible tasks using the supplied filters and pagination options."""
    return _list_tasks(db, user, filters, params)


@router.get("/me", response_model=Page[TaskOut])
def my_tasks(
    filters: TaskFilters = Depends(),
    params: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List tasks assigned to the logged-in user, retaining other task filters."""
    return _list_tasks(db, user, filters, params, force_assignee_id=user.id)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return one task after checking access to its project."""
    return _load_accessible_task(db, user, task_id)[0]


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Update a task; members may only change status on tasks assigned to them."""
    task, project = _load_accessible_task(db, user, task_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise AppError("No fields provided to update", 422, "validation_error")
    for field_name in ("title", "status", "priority"):
        if field_name in data and data[field_name] is None:
            raise AppError(f"{field_name} cannot be null", 422, "validation_error")

    if not has_permission(user, Perm.TASKS_UPDATE):
        if not has_permission(user, Perm.TASKS_UPDATE_STATUS) or task.assignee_id != user.id:
            raise ForbiddenError("You can only update tasks assigned to you")
        if set(data) - {"status"}:
            raise ForbiddenError("You may only change the status of your assigned tasks")

    if "due_date" in data and data["due_date"] != task.due_date:
        validate_deadline(project, data["due_date"])
    if "assignee_id" in data and data["assignee_id"] != task.assignee_id:
        validate_assignee(db, project, data["assignee_id"])

    changes = apply_changes(task, data)
    if changes:
        if "status" in changes:
            task.completed_at = utcnow() if task.status == TaskStatus.DONE.value else None
        task.updated_by_id = user.id
        action = "task.status_changed" if set(changes) == {"status"} else "task.updated"
        if "assignee_id" in changes:
            action = "task.assigned" if set(changes) == {"assignee_id"} else action
        log_activity(db, user, action, project_id=project.id, task_id=task.id, details=changes)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_permission(Perm.TASKS_DELETE))):
    """Delete an accessible task and record the deletion in project history."""
    task, project = _load_accessible_task(db, user, task_id)
    log_activity(db, user, "task.deleted", project_id=project.id,
                 details={"task_id": task.id, "title": task.title})
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- comments ----------
@router.post("/{task_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(task_id: int, payload: CommentCreate, db: Session = Depends(get_db),
                user: User = Depends(require_permission(Perm.COMMENTS_CREATE))):
    """Add a comment to an accessible task and record the comment event."""
    task, project = _load_accessible_task(db, user, task_id)
    comment = TaskComment(task_id=task.id, user_id=user.id, content=payload.content)
    db.add(comment)
    db.flush()
    log_activity(db, user, "task.commented", project_id=project.id, task_id=task.id,
                 details={"comment_id": comment.id})
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/{task_id}/comments", response_model=Page[CommentOut])
def list_comments(task_id: int, params: PaginationParams = Depends(), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Return comments on an accessible task in creation order."""
    task, _ = _load_accessible_task(db, user, task_id)
    stmt = select(TaskComment).where(TaskComment.task_id == task.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(TaskComment.id).offset(params.offset).limit(params.size)).unique().all()
    return make_page(CommentOut, rows, total, params)


# ---------- activity history ----------
@router.get("/{task_id}/activity", response_model=Page[ActivityOut])
def task_activity(task_id: int, params: PaginationParams = Depends(), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Return the newest audit events for an accessible task."""
    task, _ = _load_accessible_task(db, user, task_id)
    stmt = select(ActivityLog).where(ActivityLog.task_id == task.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityLog.id.desc()).offset(params.offset).limit(params.size)).unique().all()
    return make_page(ActivityOut, rows, total, params)
