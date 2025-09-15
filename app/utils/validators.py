import re
from uuid import UUID
from fastapi import HTTPException, status

def validate_uuid(id: str):
    try:
        if isinstance(id, UUID):
            return id
        return UUID(id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")

def validate_password_strength(password: str):
    pattern = re.compile(
        r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,64}$"
    )
    if not pattern.match(password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be 8-64 characters, with uppercase, lowercase, digit, and special char"
        )