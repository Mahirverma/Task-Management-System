from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from enum import Enum


class TaskLogStatus(str, Enum):
    pending = "pending"
    in_progress = "in progress"
    completed = "completed"


# ---------- Create ----------
class TaskLogCreate(BaseModel):
    task_id: UUID
    status: TaskLogStatus


# ---------- Response ----------
class TaskLogResponse(BaseModel):
    id: int
    task_id: UUID
    status: TaskLogStatus
    created_at: datetime

    class Config:
        from_attributes = True