from pydantic import BaseModel, Field
from typing import Optional, Annotated
from uuid import UUID
from datetime import datetime, date
from enum import Enum


class TaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in progress"
    completed = "completed"


# ---------- Shared ----------
class TaskBase(BaseModel):
    title: Annotated[str, Field(strip_whitespace=True, min_length=1, max_length=255)]
    description: str
    status: Optional[TaskStatus] = TaskStatus.pending


# ---------- Create ----------
class TaskCreate(TaskBase):
    assigned_to: Optional[UUID] = None
    start_date: Optional[datetime] = None
    due_date: Optional[date] = None


# ---------- Update ----------
class TaskUpdate(BaseModel):
    title: Optional[Annotated[str, Field(strip_whitespace=True, min_length=1, max_length=255)]] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    assigned_to: Optional[UUID] = None
    start_date: Optional[datetime] = None
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None


# ---------- Response ----------
class TaskResponse(TaskBase):
    uuid: UUID
    assigned_to: Optional[UUID] = None
    created_by: UUID
    created_at: datetime
    start_date: Optional[datetime] = None
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True