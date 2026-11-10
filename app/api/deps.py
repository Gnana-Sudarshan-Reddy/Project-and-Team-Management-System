"""Reusable FastAPI dependencies: DB session, current user, permission checks."""
import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.services.access import has_permission

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Validate the bearer token and load its active account from the database."""
    try:
        user_id = int(decode_access_token(token)["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token")
    user = db.get(User, user_id)
    if not user:
        raise UnauthorizedError("User no longer exists")
    if not user.is_active:
        raise ForbiddenError("Account is deactivated")
    return user


def require_permission(*perms: str):
    """Create a route dependency that requires the user to hold every permission."""

    def checker(user: User = Depends(get_current_user)) -> User:
        """Check all required permissions and return the authenticated user."""
        missing = [p for p in perms if not has_permission(user, p)]
        if missing:
            raise ForbiddenError(f"Missing permission: {', '.join(missing)}")
        return user

    return checker
