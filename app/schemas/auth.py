from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class LoginRequest(BaseModel):
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=64)

class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginResponse(BaseModel):
    message: str
    data: TokenData