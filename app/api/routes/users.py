"""Endpoints for account profiles, administration, roles, and permissions."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.permissions import ALL_PERMISSIONS, Perm, RoleName
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas.common import Message, Page, PaginationParams, make_page
from app.schemas.user import (
    PasswordChange, RoleOut, RolePermissionsUpdate, UserAdminUpdate, UserCreate, UserOut,
    UserProfileUpdate, UserRoleUpdate, UserStatusUpdate,
)
from app.services.access import get_user_or_404
from app.services.activity import log_activity
from app.services.utils import apply_changes

router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


def _ensure_email_free(db: Session, email: str, exclude_id: int | None = None) -> None:
    """Reject an email address already used by another account."""
    q = select(User).where(User.email == email.lower())
    existing = db.scalar(q)
    if existing and existing.id != exclude_id:
        raise ConflictError("Email already in use")


def _get_role_or_404(db: Session, role_id: int) -> Role:
    """Load a role by ID or raise the standard API not-found error."""
    role = db.get(Role, role_id)
    if not role:
        raise NotFoundError("Role not found")
    return role


# ---------- current user ----------
@router.get("/me", response_model=UserOut)
def read_me(user: User = Depends(get_current_user)):
    """Return the authenticated user's own profile."""
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Update the authenticated user's editable profile fields."""
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "email" in data:
        data["email"] = data["email"].lower()
        _ensure_email_free(db, data["email"], user.id)
    changes = apply_changes(user, data)
    if changes:
        log_activity(db, user, "user.profile_updated", details=changes)
    db.commit()
    return user


@router.post("/me/change-password", response_model=Message)
def change_password(payload: PasswordChange, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Verify the current password before saving its replacement."""
    if not verify_password(payload.current_password, user.hashed_password):
        raise AppError("Current password is incorrect", 400, "wrong_password")
    user.hashed_password = hash_password(payload.new_password)
    log_activity(db, user, "user.password_changed")
    db.commit()
    return Message(message="Password updated")


# ---------- admin / manager endpoints ----------
@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_permission(Perm.USERS_MANAGE))):
    """Create an account and record the administrator who created it."""
    _ensure_email_free(db, payload.email)
    if payload.role_id:
        role = _get_role_or_404(db, payload.role_id)
    else:
        role = db.scalar(select(Role).where(Role.name == RoleName.TEAM_MEMBER))
    user = User(email=payload.email.lower(), full_name=payload.full_name,
                hashed_password=hash_password(payload.password), role_id=role.id)
    db.add(user)
    db.flush()
    log_activity(db, admin, "user.created", details={"user_id": user.id, "role": role.name})
    db.commit()
    db.refresh(user)
    return user


@router.get("", response_model=Page[UserOut])
def list_users(
    q: str | None = Query(None, description="Search name or email"),
    role_id: int | None = None,
    is_active: bool | None = None,
    params: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Perm.USERS_READ)),
):
    """Search and paginate users; requires the user-read permission."""
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    if role_id is not None:
        stmt = stmt.where(User.role_id == role_id)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.id).offset(params.offset).limit(params.size)).unique().all()
    return make_page(UserOut, rows, total, params)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission(Perm.USERS_READ))):
    """Return one account to a user with permission to read users."""
    return get_user_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserAdminUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_permission(Perm.USERS_MANAGE))):
    """Change an account's administrative fields and write an audit event."""
    user = get_user_or_404(db, user_id)
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "email" in data:
        data["email"] = data["email"].lower()
        _ensure_email_free(db, data["email"], user.id)
    if "role_id" in data:
        _get_role_or_404(db, data["role_id"])
    if data.get("is_active") is False and user.id == admin.id:
        raise AppError("You cannot deactivate your own account", 400)
    changes = apply_changes(user, data)
    if changes:
        log_activity(db, admin, "user.updated", details={"user_id": user.id, **changes})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/status", response_model=UserOut)
def set_user_status(user_id: int, payload: UserStatusUpdate, db: Session = Depends(get_db),
                    admin: User = Depends(require_permission(Perm.USERS_MANAGE))):
    """Activate or deactivate an account; inactive accounts cannot use existing tokens."""
    user = get_user_or_404(db, user_id)
    if user.id == admin.id and not payload.is_active:
        raise AppError("You cannot deactivate your own account", 400)
    user.is_active = payload.is_active
    log_activity(db, admin, "user.activated" if payload.is_active else "user.deactivated",
                 details={"user_id": user.id})
    db.commit()
    return user


@router.patch("/{user_id}/role", response_model=UserOut)
def assign_role(user_id: int, payload: UserRoleUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_permission(Perm.USERS_MANAGE))):
    """Assign a role to a user while preventing admin self-demotion."""
    user = get_user_or_404(db, user_id)
    role = _get_role_or_404(db, payload.role_id)
    if user.id == admin.id and role.name != RoleName.ADMIN:
        raise AppError("You cannot remove your own admin role", 400)
    old = user.role.name
    user.role_id = role.id
    db.flush()
    log_activity(db, admin, "user.role_changed", details={"user_id": user.id, "from": old, "to": role.name})
    db.commit()
    db.refresh(user)
    return user


# ---------- roles & permissions ----------
@roles_router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """List available roles for an authenticated user."""
    return db.scalars(select(Role).order_by(Role.id)).all()


@roles_router.put("/{role_id}/permissions", response_model=RoleOut)
def set_role_permissions(role_id: int, payload: RolePermissionsUpdate, db: Session = Depends(get_db),
                         admin: User = Depends(require_permission(Perm.ROLES_MANAGE))):
    """Replace a role's permissions after validating the submitted permission names."""
    role = _get_role_or_404(db, role_id)
    unknown = set(payload.permissions) - ALL_PERMISSIONS
    if unknown:
        raise AppError(f"Unknown permissions: {sorted(unknown)}", 422, "invalid_permissions")
    if role.name == RoleName.ADMIN and not {Perm.ROLES_MANAGE, Perm.USERS_MANAGE} <= set(payload.permissions):
        raise AppError("Admin role must keep users:manage and roles:manage", 400)
    old = list(role.permissions)
    role.permissions = sorted(set(payload.permissions))
    log_activity(db, admin, "role.permissions_changed", details={"role": role.name, "from": old, "to": role.permissions})
    db.commit()
    return role
