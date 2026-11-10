"""Endpoints for viewing system-wide audit history."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Perm
from app.db.session import get_db
from app.models import ActivityLog, User
from app.schemas.common import Page, PaginationParams, make_page
from app.schemas.task import ActivityOut

router = APIRouter(prefix="/activity", tags=["Activity Logs"])


@router.get("", response_model=Page[ActivityOut])
def global_activity(
    user_id: int | None = None, project_id: int | None = None, action: str | None = None,
    params: PaginationParams = Depends(), db: Session = Depends(get_db),
    _: User = Depends(require_permission(Perm.ACTIVITY_READ_ALL)),
):
    """Return a paginated, optionally filtered system audit log."""
    stmt = select(ActivityLog)
    if user_id is not None:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(ActivityLog.project_id == project_id)
    if action:
        stmt = stmt.where(ActivityLog.action.ilike(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ActivityLog.id.desc()).offset(params.offset).limit(params.size)).unique().all()
    return make_page(ActivityOut, rows, total, params)
