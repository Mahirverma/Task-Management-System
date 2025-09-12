from pydantic import BaseModel, Field
from typing import Optional, Annotated
from uuid import UUID
from datetime import datetime, date
from decimal import Decimal


# ---------- Create ----------
class TimeLogCreate(BaseModel):
    task_id: UUID
    user_id: UUID
    date: date
    hours: Annotated[Decimal, Field(max_digits=5, decimal_places=2, ge=0)]
    notes: Annotated[str, Field(max_length=500)]


# ---------- Response ----------
class TimeLogResponse(BaseModel):
    uuid: UUID
    task_id: UUID
    user_id: UUID
    date: date
    hours: float
    notes: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True