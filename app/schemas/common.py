"""Reusable request and response schemas shared by API endpoints."""

from math import ceil
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams:
    """Validate page-number pagination and calculate the database row offset."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number (1-based)"),
        size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    ):
        """Save FastAPI-validated page and page-size query parameters."""
        self.page, self.size = page, size

    @property
    def offset(self) -> int:
        """Return the number of earlier rows to skip for this page."""
        return (self.page - 1) * self.size


class Page(BaseModel, Generic[T]):
    """Standard paginated response containing items and result counts."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def make_page(schema, rows, total: int, params: PaginationParams) -> dict:
    """Convert database rows into schema objects and package pagination details."""
    return {
        "items": [schema.model_validate(r) for r in rows],
        "total": total,
        "page": params.page,
        "size": params.size,
        "pages": ceil(total / params.size) if total else 0,
    }


class Message(BaseModel):
    """Simple response used when an endpoint returns a status message."""

    message: str
