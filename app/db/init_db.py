"""Idempotent seed: default roles (with permissions) and the first admin user."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import DEFAULT_ROLE_PERMISSIONS, ROLE_DESCRIPTIONS, RoleName
from app.core.security import hash_password
from app.models import Role, User

logger = logging.getLogger(__name__)


def seed_roles(db: Session) -> None:
    """Create any missing built-in roles without replacing existing role settings."""
    for name, perms in DEFAULT_ROLE_PERMISSIONS.items():
        if not db.scalar(select(Role).where(Role.name == name)):
            db.add(Role(name=name, description=ROLE_DESCRIPTIONS[name], permissions=perms))
    db.commit()


def seed_admin(db: Session) -> None:
    """Create the configured first administrator only when one does not exist."""
    if db.scalar(select(User).where(User.email == settings.FIRST_ADMIN_EMAIL.lower())):
        return
    admin_role = db.scalar(select(Role).where(Role.name == RoleName.ADMIN))
    db.add(User(email=settings.FIRST_ADMIN_EMAIL.lower(), full_name=settings.FIRST_ADMIN_NAME,
                hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD), role_id=admin_role.id))
    db.commit()
    logger.info("Created first admin user %s", settings.FIRST_ADMIN_EMAIL)


def init_db(db: Session) -> None:
    """Prepare baseline roles and the initial administrator account."""
    seed_roles(db)
    seed_admin(db)
