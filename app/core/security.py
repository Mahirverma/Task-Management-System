from fastapi import Depends,HTTPException, status, Cookie, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from core.config import settings
from db import get_db
from sqlalchemy.orm import Session
from models.user import User
from schemas.user import UserResponse

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalid or expired")

def get_current_user(access_token: str = Cookie(None), db: Session = Depends(get_db)) -> User:
    # Decode token
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = decode_access_token(access_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_uuid: str = payload.get("sub")
    if user_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject (sub)",
        )

    # Fetch user from DB
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user, access denied",
        )

    return user

def get_optional_user(access_token: Optional[str] = Cookie(None), db: Session = Depends(get_db)) -> Optional[User]:
    try:
        if access_token:
            return get_current_user(access_token, db)  # reuse your existing logic
        return None
    except HTTPException:
        return None