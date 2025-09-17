# app/routers/manager.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import EmailStr, BaseModel
# import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

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
from models.task import Task, TaskStatus
from models.time_log import TimeLog

# Optional Redis (for cache invalidation). If not configured, functions will be no-ops.
# try:
#     import redis
#     _redis_client = redis.from_url(settings.redis_url) if getattr(settings, "redis_url", None) else None
# except Exception:
#     _redis_client = None

router = APIRouter(prefix="/employee", tags=["Employee"])
templates = Jinja2Templates(directory="templates")
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

@router.post("/{employee_id}/profile")
def update_employee_profile(
    employee_id: str = Path(..., description="Employee UUID"),
    username: str = Form(None),
    email: str = Form(None),
    full_name: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another employee's profile")

    if not any([username, email, full_name]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field (username, email or full_name) is required")

    # Start a DB transaction and lock the row for update to prevent concurrent writes
    try:
        # lock the manager row
        employee_row = db.query(User).filter(User.id == employee_uuid).with_for_update().first()

        if not employee_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

        # Apply changes after validations
        if email:
            # validate email format via pydantic EmailStr
            email_val = email.strip()
            class TempEmailModel(BaseModel):
                email: EmailStr
            try:
                TempEmailModel(email=email_val)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")

            existing = db.query(User).filter(func.lower(User.email) == email_val.lower(), User.id != employee_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

            employee_row.email = email_val.lower()

        if username:
            username_val = username.strip()
            existing = db.query(User).filter(func.lower(User.username) == username_val.lower(), User.id != employee_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")
            employee_row.username = username_val

        if full_name is not None:
            employee_row.full_name = full_name.strip() if full_name else None

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

    return RedirectResponse(url=f"/employee/dashboard", status_code=303)

@router.post("/{employee_id}/reset_password")
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
    new_password = payload.get("new_password")

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


@router.get("/{employee_id}/profile", response_class=HTMLResponse)
def manager_profile(request: Request, employee_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    employee_uuid = validate_uuid(employee_id)
    if current_user.id != employee_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this profile")

    user = db.query(User).filter(User.id == employee_uuid).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    return templates.TemplateResponse("employee/profile.html", {"request": request, "current_user": current_user, "user": user})

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
@router.get("/dashboard", response_class=HTMLResponse)
def employee_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Only employees should access this dashboard
    if current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Show only the logged-in employee's info
    employees_data = [{
        "id": current_user.id,
        "uuid": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "task_count": db.query(func.count(Task.id)).filter(Task.assigned_to == current_user.id).scalar() or 0,
        "manager_id": current_user.created_by,
        "is_active": current_user.is_active,
    }]

    # Fetch tasks assigned to this employee (most recent first)
    tasks = db.query(Task).filter(Task.assigned_to == current_user.id).order_by(Task.created_at.desc()).all()

    # Compute status counts for this employee
    pending_count = db.query(func.count(Task.id)).filter(Task.assigned_to == current_user.id, Task.status == TaskStatus.pending).scalar() or 0
    in_progress_count = db.query(func.count(Task.id)).filter(Task.assigned_to == current_user.id, Task.status == TaskStatus.in_progress).scalar() or 0
    completed_count = db.query(func.count(Task.id)).filter(Task.assigned_to == current_user.id, Task.status == TaskStatus.completed).scalar() or 0

    status_map = {
        TaskStatus.pending: "pending",
        TaskStatus.in_progress: "in progress",
        TaskStatus.completed: "completed"
    }

    tasks_data = []
    for t in tasks:
        assigned_user = None
        if t.assigned_to:
            assigned_user = db.query(User).filter(User.id == t.assigned_to).first()
        assigned_to_name = assigned_user.username if assigned_user else None
        creator = db.query(User).filter(User.id == t.created_by).first()
        created_by_name = creator.username if creator else None

        tasks_data.append({
            "id": t.id,
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": status_map.get(t.status, str(t.status)),
            "assigned_to_name": assigned_to_name,
            "created_by_id": t.created_by,
            "created_by_name": created_by_name,
            "due_date": t.due_date.isoformat() if t.due_date else None,
        })

    task_counts = {
        "pending": pending_count,
        "in_progress": in_progress_count,
        "completed": completed_count,
        "total": pending_count + in_progress_count + completed_count
    }

    # --- Time Log extraction for the current employee ---
    time_logs = db.query(TimeLog).filter(TimeLog.user_id == current_user.id).order_by(TimeLog.date.desc(), TimeLog.created_at.desc()).all()

    time_logs_data = []
    total_logged_hours = 0
    for l in time_logs:
        # fetch task title if available
        task_obj = None
        if l.task_id:
            task_obj = db.query(Task).filter(Task.id == l.task_id).first()
        task_title = task_obj.title if task_obj else None

        time_logs_data.append({
            "id": l.id,
            "uuid": str(l.id),
            "task_id": l.task_id,
            "task_title": task_title,
            "date": l.date.isoformat() if l.date else None,
            "hours": float(l.hours) if l.hours is not None else 0.0,
            "notes": l.notes,
            "created_at": l.created_at.isoformat() if getattr(l, "created_at", None) else None,
        })
        try:
            total_logged_hours += float(l.hours or 0)
        except Exception:
            pass

    return templates.TemplateResponse(
        "employee/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "employees": employees_data,
            "tasks": tasks_data,
            "task_counts": task_counts,
            "time_logs": time_logs_data,
            "total_logged_hours": total_logged_hours,
        },
    )

@router.get("/{employee_id}/tasks/{task_id}/log-hours", response_class=HTMLResponse)
def log_hours_page(request: Request, employee_id: str = Path(...), task_id: str = Path(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Only employees should access this page
    if current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Fetch the task details
    task = db.query(Task).filter(Task.id == task_id, Task.assigned_to == employee_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return templates.TemplateResponse("employee/log_hours.html", {"request": request, "task": task, "current_user": current_user})

@router.post("/{employee_id}/tasks/{task_id}/log-hours", response_class=HTMLResponse)
def log_hours_submit(request: Request, employee_id: str = Path(...), task_id: str = Path(...), date: str = Form(...), hours: float = Form(...), notes: str = Form(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Only employees should access this page
    employee_uuid = validate_uuid(employee_id)
    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    try:
        try:
            # parse date string (expected format YYYY-MM-DD) from the form field `date`
            # note: `date` here is the form string; use datetime.strptime to avoid name collision
            log_date = datetime.strptime(date, "%Y-%m-%d").date()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD")

        if log_date > datetime.now().date():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Date cannot be in the future")

        # validate and normalize hours (single entry must be > 0 and <= 10)
        try:
            hours_decimal = Decimal(str(hours))
        except (InvalidOperation, TypeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hours value")

        if hours_decimal <= 0 or hours_decimal > Decimal("10"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Single log hours must be > 0 and <= 10")

        # Preliminary check: ensure day's total won't exceed 10 using DB aggregation (avoids loading all rows)
        try:
            prev_sum = db.query(func.coalesce(func.sum(TimeLog.hours), 0)).filter(
                TimeLog.user_id == employee_uuid,
                TimeLog.date == log_date
            ).scalar() or 0
            prev_hours = Decimal(str(prev_sum))
        except Exception:
            prev_hours = Decimal("0")

        if prev_hours + hours_decimal > Decimal("10"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Total hours for the day cannot exceed 10")
        
        total_hours = prev_hours + hours_decimal

        # Ensure task exists and is assigned to this employee
        task = db.query(Task).filter(Task.id == task_id, Task.assigned_to == employee_uuid).first()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found or not assigned to this employee")

            

        # Create a new log entry whose hours field stores the cumulative total for that date (keeps behavior consistent with existing create_log)
        log_entry = TimeLog(
            task_id=task_id,
            user_id=employee_uuid,
            date=log_date,
            hours=total_hours,
            notes=notes,
            created_at=datetime.now()
        )

        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy, try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return RedirectResponse(url=f"/employee/dashboard", status_code=303)

@router.get("/{employee_id}/time-logs/{log_id}", response_class=HTMLResponse)
def view_time_log(request: Request, employee_id: str = Path(...), log_id: str = Path(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    employee_uuid = validate_uuid(employee_id)
    log_uuid = validate_uuid(log_id)

    # allow owner or admin to view
    if current_user.id != employee_uuid and current_user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this log")

    log = db.query(TimeLog).filter(TimeLog.id == log_uuid, TimeLog.user_id == employee_uuid).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time log not found")

    task = None
    if log.task_id:
        task = db.query(Task).filter(Task.id == log.task_id).first()

    return templates.TemplateResponse("employee/view_log.html", {"request": request, "current_user": current_user, "log": log, "task": task})


@router.get("/{employee_id}/time-logs/{log_id}/edit", response_class=HTMLResponse)
def edit_time_log_page(request: Request, employee_id: str = Path(...), log_id: str = Path(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    employee_uuid = validate_uuid(employee_id)
    log_uuid = validate_uuid(log_id)

    # only owner may edit (admins could be allowed if desired; adjust check)
    if current_user.id != employee_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this log")

    log = db.query(TimeLog).filter(TimeLog.id == log_uuid, TimeLog.user_id == employee_uuid).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time log not found")

    task = None
    if log.task_id:
        task = db.query(Task).filter(Task.id == log.task_id).first()

    return templates.TemplateResponse("employee/edit_log.html", {"request": request, "current_user": current_user, "log": log, "task": task})


@router.post("/{employee_id}/time-logs/{log_id}/edit")
def edit_time_log_submit(
    employee_id: str = Path(...),
    log_id: str = Path(...),
    date: str = Form(...),
    hours: float = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)
    log_uuid = validate_uuid(log_id)

    if current_user.id != employee_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this log")

    try:
        try:
            log_date = datetime.strptime(date, "%Y-%m-%d").date()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format. Use YYYY-MM-DD")

        if log_date > datetime.now().date():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Date cannot be in the future")

        try:
            hours_decimal = Decimal(str(hours))
        except (InvalidOperation, TypeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid hours value")

        if hours_decimal <= 0 or hours_decimal > Decimal("10"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Single log hours must be > 0 and <= 10")

        # sum other logs on the same date for this user (exclude the log being edited)
        prev_sum = db.query(func.coalesce(func.sum(TimeLog.hours), 0)).filter(
            TimeLog.user_id == employee_uuid,
            TimeLog.date == log_date,
            TimeLog.id != log_uuid
        ).scalar() or 0
        prev_hours = Decimal(str(prev_sum))

        if prev_hours + hours_decimal > Decimal("10"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Total hours for the day cannot exceed 10")

        # fetch the log row with a lock for update
        log_row = db.query(TimeLog).filter(TimeLog.id == log_uuid, TimeLog.user_id == employee_uuid).with_for_update().first()
        if not log_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time log not found")

        # update fields (do not change task_id here; can be extended to allow changing task)
        log_row.date = log_date
        log_row.hours = prev_hours + hours_decimal  # keep same cumulative-style representation
        log_row.notes = notes
        log_row.created_at = getattr(log_row, "created_at", datetime.now())

        db.add(log_row)
        db.commit()
        db.refresh(log_row)

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy, try again")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return RedirectResponse(url=f"/employee/dashboard", status_code=303)


@router.delete("/{employee_id}/time-logs/{log_id}")
def delete_time_log(
    employee_id: str = Path(...),
    log_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)
    log_uuid = validate_uuid(log_id)

    if current_user.id != employee_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this log")

    try:
        log_row = db.query(TimeLog).filter(TimeLog.id == log_uuid, TimeLog.user_id == employee_uuid).with_for_update().first()
        if not log_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time log not found")

        db.delete(log_row)
        db.commit()

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy, try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    return JSONResponse(status_code=200, content={
        "message": "Time Log deleted successfully",
        "data": {"uuid": str(log_uuid)}
    })