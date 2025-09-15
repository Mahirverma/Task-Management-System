# app/routers/manager.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
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

# Optional Redis (for cache invalidation). If not configured, functions will be no-ops.
# try:
#     import redis
#     _redis_client = redis.from_url(settings.redis_url) if getattr(settings, "redis_url", None) else None
# except Exception:
#     _redis_client = None

router = APIRouter(prefix="/admin", tags=["Admin"])

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

@router.patch("/{admin_id}/profile")
def update_admin_profile(
    admin_id: str = Path(..., description="Admin UUID"),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    if current_user.id != admin_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another admin's profile")

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must contain payload")

    username = payload.get("username")
    email = payload.get("email")
    full_name = payload.get("full_name")

    # Start a DB transaction and lock the row for update to prevent concurrent writes
    try:
        # lock the manager row
        admin_row = db.query(User).filter(User.id == admin_uuid).with_for_update().first()

        if not admin_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")

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

            existing = db.query(User).filter(func.lower(User.email) == email.lower(), User.id == admin_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

            admin_row.email = email.strip().lower()

        if username:
            username = username.strip()
            existing = db.query(User).filter(func.lower(User.username) == username.lower(), User.id == admin_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")
            admin_row.username = username

        if full_name:
            admin_row.full_name = full_name.strip()

        db.add(admin_row)
        db.commit()
        db.refresh(admin_row)

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
        "message": "Admin profile updated successfully",
        "data": {
            "uuid": str(admin_row.id),
            "username": admin_row.username,
            "email": admin_row.email,
            "full_name": admin_row.full_name,
            "role": admin_row.role.value if hasattr(admin_row.role, "value") else str(admin_row.role),
        },
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.post("/{admin_id}/managers")
def create_manager(
    admin_id: str = Path(..., description="Admin UUID"),
    payload: dict = None,
    # background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    if current_user.id != admin_uuid or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the admin can create their managers")

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must contain payload")

    username = payload.get("username")
    email = payload.get("email")
    password = payload.get("password")
    full_name = payload.get("full_name","")

    if not username or not email or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username, email and password are required")

    class TempEmailModel(BaseModel):
                email: EmailStr
    try:
        TempEmailModel(email=email)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")

    existing = db.query(User).filter((func.lower(User.email) == email.lower()) | (func.lower(User.username) == username.lower())).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists")

    new_user = User(
        username=username.strip(),
        email=email.strip().lower(),
        full_name=(full_name.strip() if full_name else None),
        role=UserRole.manager,
        password_hash=hash_password(password),
        is_active=True,
        created_by=current_user.id,
        created_at=datetime.now(),
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict creating employee")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # Invalidate cache
    # _invalidate_manager_cache(manager_uuid)

    # Send welcome email in background
    # if background_tasks is not None and getattr(settings, "smtp_host", None):
    #     subject = "Welcome — account created"
    #     body = f"Hello {new_user.username},\n\nAn account has been created for you. Please login with your credentials.\n"
    #     background_tasks.add_task(send_email, new_user.email, subject, body)

    resp = {
        "message": "Manager created successfully",
        "data": {
            "uuid": str(new_user.id),
            "username": new_user.username,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": "manager",
            "created_by": str(new_user.created_by),
        },
    }
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp)


@router.get("/{admin_id}/managers")
def list_managers(
    admin_id: str = Path(..., description="Admin UUID"),
    limit: int = Query(40, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    if limit > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit exceeds maximum of 100")

    if current_user.id != admin_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view these managers")

    managers = db.query(User).filter(
        User.created_by == admin_uuid,
        User.role == UserRole.manager,
        User.is_active == True
    ).order_by(User.username).limit(limit).offset(offset).all()

    data=[]
    for m in managers:
        employees = db.query(User).filter(
            User.created_by == m.id,
            User.role == UserRole.employee,
            User.is_active == True
        ).order_by(User.username).all()
        data.append({
            "uuid": str(m.id),
            "username": m.username,
            "email": m.email,
            "full_name": m.full_name,
            "role": "manager",
            "employees": [
                {
                    "uuid": str(e.id),
                    "username": e.username,
                    "email": e.email,
                    "full_name": e.full_name,
                    "role": "employee"
                } for e in employees
            ]
        })

    resp = {
        "message": "Managers fetched successfully",
        "data": data
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.get("/{admin_id}/managers/{manager_id}")
def get_manager(
    admin_id: str = Path(...),
    manager_id: str = Path(...),
    limit: int = Query(40, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)
    manager_uuid = validate_uuid(manager_id)

    if limit > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit exceeds maximum of 100")

    if current_user.role == UserRole.admin and current_user.id != admin_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    manager = db.query(User).filter(User.id == manager_uuid, User.role == UserRole.manager, User.created_by == admin_uuid).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

    employees = db.query(User).filter(User.created_by == manager_uuid,
        User.role == UserRole.employee,
        User.is_active == True).order_by(User.username).limit(limit).offset(offset).all()
    
    data = []
    data.append({
            "uuid": str(manager.id),
            "username": manager.username,
            "email": manager.email,
            "full_name": manager.full_name,
            "role": "manager",
            "employees": [
                {
                    "uuid": str(e.id),
                    "username": e.username,
                    "email": e.email,
                    "full_name": e.full_name,
                    "role": "employee"
                } for e in employees
            ]
        })

    resp = {
        "message": "Manager fetched successfully",
        "data": data
    }   
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.put("/{admin_id}/reset_password")
def reset_admin_password(
    admin_id: str = Path(...),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    if current_user.id != admin_uuid or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request body must contain payload")

    current_password = payload.get("current_password")
    new_password = payload.get("new_password")

    if not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password required")

    if current_password:
        if not verify_password(current_password, current_user.password_hash):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password incorrect")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password required to reset password")

    try:
        admin_row = db.query(User).filter(User.id == admin_uuid).with_for_update().first()
        if not admin_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")

        admin_row.password_hash = hash_password(new_password)
        db.add(admin_row)
        db.commit()
        db.refresh(admin_row)
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset password")

    # Invalidate caches and (optionally) revoke tokens via token_version bump (not implemented here)
    # _invalidate_manager_cache(manager_uuid)

    resp = {"message": "Password updated successfully. Login again.", "data": {"uuid": str(admin_uuid)}}
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.patch("/{admin_id}/users/{manager_id}/deactivate")
def deactivate_manager(
    admin_id: str = Path(...),
    manager_id: str = Path(...),
    # payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)
    manager_uuid = validate_uuid(manager_id)

    if current_user.id != admin_uuid or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if admin_uuid == manager_uuid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate self")

    manager = db.query(User).filter(User.id == manager_uuid, User.role == UserRole.manager).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

    if manager.created_by != admin_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager not under this admin")

    if not manager.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager already inactive")

    try:
        manager.is_active = False
        db.add(manager)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to deactivate manager")

    # _invalidate_manager_cache(manager_uuid)

    resp = {
        "message": "Employee deactivated successfully",
        "data": {"uuid": str(manager_uuid), "is_active": False},
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)

@router.patch("/{admin_id}/users/{manager_id}/activate")
def activate_manager(
    admin_id: str = Path(...),
    manager_id: str = Path(...),
    # payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)
    manager_uuid = validate_uuid(manager_id)

    if current_user.id != admin_uuid or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if admin_uuid == manager_uuid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate self")

    manager = db.query(User).filter(User.id == manager_uuid, User.role == UserRole.manager).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

    if manager.created_by != admin_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager not under this admin")

    if manager.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager already active")

    try:
        manager.is_active = True
        db.add(manager)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to activate manager")

    # _invalidate_manager_cache(manager_uuid)

    resp = {
        "message": "Employee activated successfully",
        "data": {"uuid": str(manager_uuid), "is_active": True},
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)
