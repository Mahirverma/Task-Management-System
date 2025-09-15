# app/routers/manager.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body
from fastapi.responses import JSONResponse
from pydantic import EmailStr, BaseModel
# import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from passlib.context import CryptContext

# from core.config import settings
from db import get_db
from models.user import User, UserRole
from core.security import hash_password,verify_password, get_current_user
from utils.email_utils import send_email
from utils.validators import validate_uuid
from models.time_log import TimeLog

# Optional Redis (for cache invalidation). If not configured, functions will be no-ops.
# try:
#     import redis
#     _redis_client = redis.from_url(settings.redis_url) if getattr(settings, "redis_url", None) else None
# except Exception:
#     _redis_client = None

router = APIRouter(prefix="/employee", tags=["Employee"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# def _invalidate_manager_cache(manager_uuid: UUID):
#     """Invalidate Redis keys used for manager employee lists. Implement key naming consistently with your cache usage."""
#     if not _redis_client:
#         return
#     try:
#         # example key patterns
#         keys = [f"manager:{manager_uuid}:employees", f"manager:{manager_uuid}:employees:active"]
#         for k in keys:
#             _redis_client.delete(k)
#     except Exception:
#         # don't crash the request if cache invalidation fails
#         pass

# ----------------- Endpoints -----------------

@router.patch("/{employee_id}/profile")
def update_employee_profile(
    employee_id: str = Path(..., description="Employee UUID"),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another employee's profile")

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must contain payload")

    username = payload.get("username")
    email = payload.get("email")
    full_name = payload.get("full_name")

    # Start a DB transaction and lock the row for update to prevent concurrent writes
    try:
        # lock the manager row
        employee_row = db.query(User).filter(User.id == employee_uuid).with_for_update().first()

        if not employee_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

        # Apply changes after validations
        if email:
            # validate email format via pydantic EmailStr
            email = email.strip()
            class TempEmailModel(BaseModel):
                email: EmailStr
            try:
                TempEmailModel(email=email)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")

            existing = db.query(User).filter(func.lower(User.email) == email.lower(), User.id == employee_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

            employee_row.email = email.strip().lower()

        if username:
            username = username.strip()
            existing = db.query(User).filter(func.lower(User.username) == username.lower(), User.id == employee_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")
            employee_row.username = username

        if full_name:
            employee_row.full_name = full_name.strip()

        db.add(employee_row)
        db.commit()
        db.refresh(employee_row)

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database is busy, try again")
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict during update")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Invalidate redis cache for this manager
    # _invalidate_manager_cache(manager_uuid)

    resp = {
        "message": "Employee profile updated successfully",
        "data": {
            "uuid": str(employee_row.id),
            "username": employee_row.username,
            "email": employee_row.email,
            "full_name": employee_row.full_name,
            "role": employee_row.role.value if hasattr(employee_row.role, "value") else str(employee_row.role),
        },
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)

@router.put("/{employee_id}/reset_password")
def reset_employee_password(
    employee_id: str = Path(...),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must contain payload")

    current_password = payload.get("current_password")
    new_password = payload.get("password")

    if not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password required")

    if current_password:
        if not verify_password(current_password, current_user.password_hash):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password incorrect")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password required to reset password")

    try:
        employee_row = db.query(User).filter(User.id == employee_uuid).with_for_update().first()
        if not employee_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

        employee_row.password_hash = hash_password(new_password)
        db.add(employee_row)
        db.commit()
        db.refresh(employee_row)
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset password")

    # Invalidate caches and (optionally) revoke tokens via token_version bump (not implemented here)
    # _invalidate_manager_cache(manager_uuid)

    resp = {"message": "Password updated successfully. Login again.", "data": {"uuid": str(employee_uuid)}}
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)

@router.post("/{employee_id}/logs")
def create_log(
    employee_id: str = Path(..., description="Employee UUID"),
    payload: dict = None,
    # background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)
    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not payload:
        raise HTTPException(status_code=400, detail="Missing payload in request body")
    
    task_id = payload.get("task_id")
    date = payload.get("date")
    hours = payload.get("hours")
    notes = payload.get("notes")

    try:
        log_data = TimeLog(
            task_id = task_id,
            user_id = employee_uuid,
            date = date,
            hours = hours,
            notes = notes,
            created_at = datetime.now()
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if log_data.date > date.today():
        raise HTTPException(status_code=400, detail="Date cannot be in the future")

    # Check total hours for same day
    existing_hours = db.query(TimeLog).filter(
        TimeLog.user_id == employee_uuid,
        TimeLog.date == log_data.date
    ).with_for_update().all()
    if existing_hours:
        total_hours = sum(l.hours for l in existing_hours) + log_data.hours
        log_data.hours = total_hours

    try:
        db.add(log_data)
        db.commit()
        db.refresh(log_data)
        # invalidate_employee_cache(employee_uuid)

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Database busy, try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(status_code=201, content={
        "message": "Log submitted successfully",
        "data": {
            "uuid": str(employee_uuid),
            "date": log_data.date.isoformat(),
            "hours": log_data.hours,
            "notes": log_data.notes
        }
    })