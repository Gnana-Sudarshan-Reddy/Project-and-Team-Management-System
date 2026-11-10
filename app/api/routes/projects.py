"""Endpoints for project management, membership, statistics, and history."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.exceptions import AppError, ConflictError
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import ActivityLog, Project, ProjectMember, Task, User
from app.models.enums import ProjectStatus, TaskPriority, TaskStatus
from app.schemas.common import Page, PaginationParams, make_page
from app.schemas.project import (
    AssigneeStat, MemberAdd, ProjectCreate, ProjectDetail, ProjectOut, ProjectStats, ProjectUpdate,
)
from app.schemas.task import ActivityOut
from app.schemas.user import UserBrief
from app.services.access import (
    accessible_project_ids, ensure_project_access, ensure_project_owner, get_project_or_404,
    get_user_or_404, is_admin,
)
from app.services.activity import log_activity
from app.services.utils import apply_changes, plain

router = APIRouter(prefix="/projects", tags=["Projects"])


def _detail(project: Project) -> ProjectDetail:
    """Convert a project ORM object to its detailed API response schema."""
    return ProjectDetail.model_validate(project)


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_permission(Perm.PROJECTS_CREATE))):
    """Create a project and add its owner plus any requested members."""
    member_ids = set(payload.member_ids) | {user.id}
    found = db.scalars(select(User).where(User.id.in_(member_ids))).unique().all()
    missing = member_ids - {u.id for u in found}
    if missing:
        raise AppError(f"Users not found: {sorted(missing)}", 404, "not_found")
    if any(not u.is_active for u in found):
        raise AppError("Cannot add deactivated users to a project", 422, "inactive_user")

    data = payload.model_dump(exclude={"member_ids"})
    data["status"] = plain(data["status"])
    project = Project(**data, owner_id=user.id)
    project.members = [ProjectMember(user_id=uid) for uid in member_ids]
    db.add(project)
    db.flush()
    log_activity(db, user, "project.created", project_id=project.id, details={"name": project.name})
    db.commit()
    db.refresh(project)
    return _detail(project)


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    q: str | None = Query(None, description="Search in name"),
    status_: ProjectStatus | None = Query(None, alias="status"),
    owner_id: int | None = None,
    params: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return projects visible to the user, with optional filters and pagination."""
    stmt = select(Project)
    if not is_admin(user):
        stmt = stmt.where(Project.id.in_(accessible_project_ids(user)))
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{q}%"))
    if status_:
        stmt = stmt.where(Project.status == status_.value)
    if owner_id is not None:
        stmt = stmt.where(Project.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Project.created_at.desc(), Project.id.desc())
                      .offset(params.offset).limit(params.size)).all()
    return make_page(ProjectOut, rows, total, params)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return one project after checking that the current user can access it."""
    return _detail(ensure_project_access(db, user, project_id))


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require_permission(Perm.PROJECTS_UPDATE))):
    """Update an owned project and record changed fields in the audit history."""
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, user)
    data = payload.model_dump(exclude_unset=True)
    for field_name in ("name", "status"):  # These database columns are required.
        if field_name in data and data[field_name] is None:
            raise AppError(f"{field_name} cannot be null", 422, "validation_error")
    start = data.get("start_date", project.start_date)
    end = data.get("end_date", project.end_date)
    if start and end and end < start:
        raise AppError("end_date cannot be before start_date", 422, "validation_error")
    changes = apply_changes(project, data)
    if changes:
        log_activity(db, user, "project.updated", project_id=project.id, details=changes)
    db.commit()
    db.refresh(project)
    return _detail(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_permission(Perm.PROJECTS_DELETE))):
    """Delete an owned project while preserving its project-deletion audit event."""
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, user)
    log_activity(db, user, "project.deleted", details={"project_id": project.id, "name": project.name})
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- members ----------
@router.get("/{project_id}/members", response_model=list[UserBrief])
def list_members(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """List users who belong to a project the current user can access."""
    project = ensure_project_access(db, user, project_id)
    return [m.user for m in project.members]


@router.post("/{project_id}/members", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def add_member(project_id: int, payload: MemberAdd, db: Session = Depends(get_db),
               user: User = Depends(require_permission(Perm.PROJECTS_MEMBERS))):
    """Add an active user to a project owned by the current user or an admin."""
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, user)
    target = get_user_or_404(db, payload.user_id)
    if not target.is_active:
        raise AppError("Cannot add a deactivated user", 422, "inactive_user")
    if any(m.user_id == target.id for m in project.members):
        raise ConflictError("User is already a project member")
    project.members.append(ProjectMember(user_id=target.id))
    log_activity(db, user, "project.member_added", project_id=project.id, details={"user_id": target.id})
    db.commit()
    db.refresh(project)
    return _detail(project)


@router.delete("/{project_id}/members/{user_id}", response_model=ProjectDetail)
def remove_member(project_id: int, user_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_permission(Perm.PROJECTS_MEMBERS))):
    """Remove a project member and unassign that user's tasks in the project."""
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, user)
    if user_id == project.owner_id:
        raise AppError("The project owner cannot be removed", 400)
    member = next((m for m in project.members if m.user_id == user_id), None)
    if not member:
        raise AppError("User is not a member of this project", 404, "not_found")
    project.members.remove(member)
    # Keep task assignments valid after the user leaves the project.
    unassigned = db.scalars(select(Task).where(Task.project_id == project.id, Task.assignee_id == user_id)).all()
    for t in unassigned:
        t.assignee_id = None
    log_activity(db, user, "project.member_removed", project_id=project.id,
                 details={"user_id": user_id, "tasks_unassigned": len(unassigned)})
    db.commit()
    db.refresh(project)
    return _detail(project)


# ---------- stats & activity ----------
@router.get("/{project_id}/stats", response_model=ProjectStats)
def project_stats(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Summarize task progress, deadlines, priorities, and assignees for a project."""
    project = ensure_project_access(db, user, project_id)
    by_status = {s.value: 0 for s in TaskStatus}
    by_priority = {p.value: 0 for p in TaskPriority}
    for task_status, task_count in db.execute(
        select(Task.status, func.count())
        .where(Task.project_id == project.id)
        .group_by(Task.status)
    ):
        by_status[task_status] = task_count
    for task_priority, task_count in db.execute(
        select(Task.priority, func.count())
        .where(Task.project_id == project.id)
        .group_by(Task.priority)
    ):
        by_priority[task_priority] = task_count
    total = sum(by_status.values())
    done = by_status[TaskStatus.DONE.value]
    overdue = db.scalar(select(func.count()).where(
        Task.project_id == project.id, Task.due_date < date.today(), Task.status != TaskStatus.DONE.value)) or 0
    rows = db.execute(
        select(
            Task.assignee_id,
            User.full_name,
            func.count(Task.id).label("total_tasks"),
            func.sum(case((Task.status == TaskStatus.DONE.value, 1), else_=0)).label(
                "completed_tasks"
            ),
        )
        .outerjoin(User, User.id == Task.assignee_id)
        .where(Task.project_id == project.id)
        .group_by(Task.assignee_id, User.full_name)
    ).all()
    return ProjectStats(
        project_id=project.id, total_tasks=total, completed_tasks=done, overdue_tasks=overdue,
        progress_percent=round(done / total * 100, 1) if total else 0.0,
        by_status=by_status, by_priority=by_priority,
        by_assignee=[
            AssigneeStat(
                user_id=row.assignee_id,
                full_name=row.full_name,
                total=row.total_tasks,
                done=int(row.completed_tasks or 0),
            )
            for row in rows
        ],
    )


@router.get("/{project_id}/activity", response_model=Page[ActivityOut])
def project_activity(project_id: int, params: PaginationParams = Depends(), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Return the paginated audit history for an accessible project."""
    ensure_project_access(db, user, project_id)
    stmt = select(ActivityLog).where(ActivityLog.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityLog.id.desc()).offset(params.offset).limit(params.size)).unique().all()
    return make_page(ActivityOut, rows, total, params)
