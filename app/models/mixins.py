"""Shared timestamp fields and UTC clock helper for database models."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Return the current time in UTC for consistent stored timestamps."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Add creation and last-update timestamps to a SQLAlchemy model."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
