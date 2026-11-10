"""Public account registration and OAuth2 password login endpoints."""

import logging

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.permissions import RoleName
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User
from app.schemas.user import RegisterRequest, Token, UserOut
from app.services.activity import log_activity

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a Team Member account and record the registration in the audit log."""
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("Email already registered")
    role = db.scalar(select(Role).where(Role.name == RoleName.TEAM_MEMBER))
    user = User(email=email, full_name=payload.full_name, hashed_password=hash_password(payload.password),
                role_id=role.id)
    db.add(user)
    db.flush()
    log_activity(db, user, "user.registered", details={"email": email})
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Verify form credentials and return a bearer token for an active account."""
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.hashed_password):
        logger.warning("Failed login for %s", form.username)
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise ForbiddenError("Account is deactivated")
    log_activity(db, user, "user.login")
    db.commit()
    return Token(access_token=create_access_token(user.id), user=UserOut.model_validate(user))
