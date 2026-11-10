"""Validation and response schemas for users, roles, passwords, and tokens."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_FIELD = Field(min_length=8, max_length=64)


def _check_password_strength(v: str) -> str:
    """Require passwords to contain both letters and digits."""
    if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
        raise ValueError("Password must contain at least one letter and one digit")
    return v


class RoleOut(BaseModel):
    """Role name and permissions safe to return through the API."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None
    permissions: list[str] = []


class RolePermissionsUpdate(BaseModel):
    """Replacement permission list submitted when editing a role."""

    permissions: list[str]


class UserBrief(BaseModel):
    """Small public user representation used in related API responses."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: EmailStr


class UserOut(UserBrief):
    """User profile response that includes account state and role."""

    is_active: bool
    role: RoleOut
    created_at: datetime


class RegisterRequest(BaseModel):
    """Public sign-up fields, including the minimum password requirements."""

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = PASSWORD_FIELD

    _pw = field_validator("password")(_check_password_strength)


class UserCreate(RegisterRequest):
    """Administrator-created user; omitted role IDs default to Team Member."""
    role_id: int | None = None


class UserProfileUpdate(BaseModel):
    """Fields a signed-in user may change on their own profile."""

    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None


class UserAdminUpdate(UserProfileUpdate):
    """Additional profile fields that an authorized administrator may change."""

    role_id: int | None = None
    is_active: bool | None = None


class UserStatusUpdate(BaseModel):
    """Request body for activating or deactivating an account."""

    is_active: bool


class UserRoleUpdate(BaseModel):
    """Request body for changing a user's role."""

    role_id: int


class PasswordChange(BaseModel):
    """Current and replacement passwords for an authenticated account."""

    current_password: str
    new_password: str = PASSWORD_FIELD

    _pw = field_validator("new_password")(_check_password_strength)


class Token(BaseModel):
    """Login response containing the bearer token and signed-in user."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
