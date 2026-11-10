"""Validation and response schemas for tasks, comments, and audit events."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.user import UserBrief


class TaskCreate(BaseModel):
    """Fields required or optionally accepted when creating a task."""

    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    project_id: int
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None
    assignee_id: int | None = None


class TaskUpdate(BaseModel):
    """Fields that may be changed when updating a task."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
    assignee_id: int | None = None


class TaskOut(BaseModel):
    """Task fields returned by API endpoints, including computed overdue state."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: date | None
    project_id: int
    assignee: UserBrief | None
    created_by: UserBrief | None
    updated_by: UserBrief | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @computed_field
    @property
    def is_overdue(self) -> bool:
        """Mark unfinished tasks overdue when their due date has passed."""
        return bool(self.due_date and self.due_date < date.today() and self.status != TaskStatus.DONE)


class CommentCreate(BaseModel):
    """Request body for adding a comment to a task."""

    content: str = Field(min_length=1, max_length=5000)


class CommentOut(BaseModel):
    """Comment details returned by the API."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    content: str
    user: UserBrief
    created_at: datetime


class ActivityOut(BaseModel):
    """Audit event details returned by activity endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    user: UserBrief | None
    project_id: int | None
    task_id: int | None
    details: dict | None
    created_at: datetime
