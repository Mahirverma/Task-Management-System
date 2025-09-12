from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Annotated
from uuid import UUID
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    employee = "employee"


# ---------- Shared ----------
class UserBase(BaseModel):
    username: Annotated[str,Field(strip_whitespace=True, min_length=3, max_length=150)]
    email: Annotated[EmailStr, Field(min_length=5, max_length=255, strip_whitespace=True)]
    full_name: Optional[Annotated[str,Field(max_length=255)]] = None
    role: UserRole
    is_active: Optional[bool] = True


# ---------- Create ----------
class UserCreate(UserBase):
    password: Annotated[str, Field(min_length=6, max_length=128, strip_whitespace=True)]  # incoming plain password


# ---------- Update ----------
class UserUpdate(BaseModel):
    username: Optional[Annotated[str, Field(strip_whitespace=True, min_length=3, max_length=150)]] = None
    email: Optional[Annotated[EmailStr, Field(min_length=5, max_length=255, strip_whitespace=True)]] = None
    full_name: Optional[Annotated[str, Field(max_length=255)]] = None
    is_active: Optional[bool]


# ---------- Response ----------
class UserResponse(UserBase):
    uuid: UUID
    created_by: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True