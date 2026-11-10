"""Helpers for normalizing values and applying tracked model changes."""

from datetime import date, datetime
from enum import Enum
from typing import Any


def plain(value: Any) -> Any:
    """Convert enums and dates to values suitable for database columns and JSON."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def apply_changes(obj: Any, data: dict) -> dict:
    """Apply changed fields and return their old/new values for audit logging."""
    changes = {}
    for field, new in data.items():
        new_plain = plain(new)
        old_plain = plain(getattr(obj, field))
        if old_plain != new_plain:
            changes[field] = {"from": old_plain, "to": new_plain}
            setattr(obj, field, new_plain if isinstance(new, Enum) else new)
    return changes
