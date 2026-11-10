"""Validation and response schemas for projects and project statistics."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ProjectStatus
from app.schemas.user import UserBrief


class ProjectBase(BaseModel):
    """Fields shared by project creation and project details."""

    name: str = Field(min_length=3, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus = ProjectStatus.PLANNING
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _check_dates(self):
        """Reject a project whose end date occurs before its start date."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class ProjectCreate(ProjectBase):
    """Input for creating a project, optionally including its initial members."""

    member_ids: list[int] = []


class ProjectUpdate(BaseModel):
    """Optional fields accepted when changing an existing project."""

    name: str | None = Field(default=None, min_length=3, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    status: ProjectStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class ProjectOut(BaseModel):
    """Public project fields returned by list and detail endpoints."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    status: ProjectStatus
    start_date: date | None
    end_date: date | None
    owner: UserBrief
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectOut):
    """Project response that also includes its member accounts."""

    members: list[UserBrief]

    @field_validator("members", mode="before")
    @classmethod
    def _unwrap_members(cls, v):
        """Expose each member's user instead of the join-table record."""
        return [getattr(m, "user", m) for m in v]


class MemberAdd(BaseModel):
    """Request body identifying the user to add to a project."""

    user_id: int


class AssigneeStat(BaseModel):
    """Task totals and completions for one assignee in a project."""

    user_id: int | None
    full_name: str | None
    total: int
    done: int


class ProjectStats(BaseModel):
    """Project-wide task counts, progress, and grouped summaries."""

    project_id: int
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    progress_percent: float
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_assignee: list[AssigneeStat]
