# app/routers/manager.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse,HTMLResponse, RedirectResponse
from pydantic import EmailStr, BaseModel
# import uuid
from datetime import datetime

from sqlalchemy import func, asc, desc
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, aliased

from passlib.context import CryptContext

# from core.config import settings
from db import get_db
from models.user import User, UserRole
from models.task import Task, TaskStatus as ts
from models.task_log import TaskLog, TaskStatus
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
templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
creator = aliased(User)

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

@router.post("/{admin_id}/profile")
def update_admin_profile(
    request: Request,
    admin_id: str = Path(..., description="Admin UUID"),
    username: str = Form(None),
    email: str = Form(None),
    full_name: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    # only the admin themselves may update their profile via the HTML form
    if current_user.id != admin_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another admin's profile")

    if not any([username, email, full_name]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field (username, email or full_name) is required")

    try:
        admin_row = db.query(User).filter(User.id == admin_uuid).with_for_update().first()
        if not admin_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")

        if email:
            email_val = email.strip()
            class TempEmailModel(BaseModel):
                email: EmailStr
            try:
                TempEmailModel(email=email_val)
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")

            # ensure no other user has this email
            existing = db.query(User).filter(func.lower(User.email) == email_val.lower(), User.id != admin_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

            admin_row.email = email_val.lower()

        if username:
            username_val = username.strip()
            existing = db.query(User).filter(func.lower(User.username) == username_val.lower(), User.id != admin_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")
            admin_row.username = username_val

        if full_name is not None:
            admin_row.full_name = full_name.strip() if full_name else None

        db.add(admin_row)
        db.commit()
        db.refresh(admin_row)

    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database is busy, try again")
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict during update")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    # After successful update redirect back to the profile page so the template can show updated data
    return RedirectResponse(url=f"/admin/dashboard", status_code=303)


@router.get("/{admin_id}/profile", response_class=HTMLResponse)
def admin_profile(request: Request, admin_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    admin_uuid = validate_uuid(admin_id)
    if current_user.id != admin_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this profile")

    user = db.query(User).filter(User.id == admin_uuid).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")

    return templates.TemplateResponse("admin/profile.html", {"request": request, "current_user": current_user, "user": user})


@router.post("/{admin_id}/managers")
def create_manager(
    admin_id: str = Path(..., description="Admin UUID"),
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    # background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    admin_uuid = validate_uuid(admin_id)

    if current_user.id != admin_uuid or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the admin can create their managers")

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

    # resp = {
    #     "message": "Manager created successfully",
    #     "data": {
    #         "uuid": str(new_user.id),
    #         "username": new_user.username,
    #         "email": new_user.email,
    #         "full_name": new_user.full_name,
    #         "role": "manager",
    #         "created_by": str(new_user.created_by),
    #     },
    # }
    # return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp)
    return RedirectResponse(url = f'/admin/dashboard', status_code=303)


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


@router.get("/{admin_id}/managers/{manager_id}", response_class=HTMLResponse)
def get_manager(
    request: Request,
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
    manager.role = "Manager"

    employees = db.query(User).filter(User.created_by == manager_uuid,
        User.role == UserRole.employee,
        User.is_active == True).order_by(User.username).limit(limit).offset(offset).all()
    for e in employees:
        e.role = "Employee"
    data = []
    for emp in employees:
            # fetch tasks for this employee (small summary)
            emp_tasks = db.query(Task).filter(Task.assigned_to == emp.id).order_by(Task.created_at.desc()).all()
            data.append({
            "uuid": str(emp.id),
            "username": emp.username,
            "email": emp.email,
            "full_name": emp.full_name,
            "role": "employee",
            "manager_id": emp.created_by,
            "task_count": len(emp_tasks),
            "tasks": [
                {
                    "uuid": str(t.id),
                    "title": t.title,
                    "description": t.description,
                    "status": t.status.value,
                    "due_date": t.due_date.isoformat() if t.due_date else None
                } for t in emp_tasks
            ]
        })
    
    return templates.TemplateResponse(
        "admin/manager_detail.html",
        {
            "request": request,
            "manager": manager,
            "employees": data,
            "current_user": current_user
        },
    )


@router.post("/{admin_id}/reset_password")
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

@router.patch("/{admin_id}/managers/{manager_id}/activate")
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


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # validate token
):
    # ✅ ensure only admin can access
    if current_user.role != UserRole.admin:
        return HTMLResponse("<h3>Access Denied</h3>", status_code=403)

    # Fetch managers (same logic you had in /{admin_id}/managers)
    managers = db.query(User).filter(
        User.created_by == current_user.id,
        User.role == UserRole.manager
    ).order_by(asc(User.username)).all()

    data = []
    all_employees = []
    all_tasks = []
    for m in managers:
        employees = db.query(User).filter(
        User.created_by == m.id,
        User.role == UserRole.employee,
    ).order_by(asc(User.username)).all()

        data.append({
        "uuid": str(m.id),
        "username": m.username,
        "email": m.email,
        "full_name": m.full_name,
        "role": "manager",
        "employee_count": len(employees),  # 🔹 only count
        "is_active": m.is_active,
        })

        for emp in employees:
            t = db.query(Task).filter(Task.assigned_to == emp.id).count()
            all_employees.append({
            "uuid": str(emp.id),
            "username": emp.username,
            "email": emp.email,
            "full_name": emp.full_name,
            "role": "employee",
            "task_count": t,
            "manager_id": str(m.id),  # optional: to know which manager they belong to
        })
        ts_map ={
            ts.pending: "pending",
            ts.in_progress: "in progress",
            ts.completed: "completed"
        }
        tasks = db.query(Task).filter(Task.created_by == m.id).all()
        task_id=[]
        for t in tasks:
            task_id.append(t.id)
            all_tasks.append({
            "uuid": str(t.id),
            "title": t.title,           # adjust field names as per your Task model
            "description": t.description,
            "created_by_id": str(t.created_by),
            "created_by_name": m.username,
            "status": ts_map[t.status],
        })
            log_status_map = {
                TaskStatus.pending: "pending",
                TaskStatus.in_progress: "in progress",
                TaskStatus.completed: "completed"
            }
            task_logs = db.query(TaskLog).filter(TaskLog.task_id.in_(task_id)).order_by(TaskLog.created_at.desc()).all()
            logs_list = []
            for log in task_logs:
                logs_list.append({
                "log_id": str(log.id),
                "task_id": str(log.task_id),
                "task_name": t.title,
                "status": log_status_map[log.status],
                "timestamp": log.created_at.isoformat()
            })

    # Render the dashboard template
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "managers": data, "employees": all_employees, "tasks": all_tasks, "task_log": logs_list, "current_user": current_user}
    )

@router.get("/{admin_id}/create-manager")
def create_manager_page(
    request: Request,
    admin_id: str = Path(..., description="Admin UUID"),
    current_user: User = Depends(get_current_user)
):
    # Optional: verify that current_user is the same admin
    if str(current_user.id) != str(admin_id) or current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return templates.TemplateResponse(
        "admin/create_manager.html",
        {"request": request, "admin_id": admin_id}
    )

@router.get("/managers", response_class=HTMLResponse)
def managers_table(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # validate token
):
    # ✅ ensure only admin can access
    if current_user.role != UserRole.admin:
        return HTMLResponse("<h3>Access Denied</h3>", status_code=403)

    # Fetch managers (same logic you had in /{admin_id}/managers)
    managers = db.query(User).filter(
        User.created_by == current_user.id,
        User.role == UserRole.manager
    ).order_by(asc(User.username)).all()

    data = []
    for m in managers:
        employees = db.query(User).filter(
        User.created_by == m.id,
        User.role == UserRole.employee,
    ).order_by(asc(User.username)).all()

        data.append({
        "uuid": str(m.id),
        "username": m.username,
        "email": m.email,
        "full_name": m.full_name,
        "role": "manager",
        "employee_count": len(employees),  # 🔹 only count
        "is_active": m.is_active,
        })

    # Render the dashboard template
    return templates.TemplateResponse(
        "admin/managers.html",
        {"request": request, "managers": data, "current_user": current_user}
    )

@router.get("/employees", response_class=HTMLResponse)
def employees(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # validate token
):
    # ✅ ensure only admin can access
    if current_user.role != UserRole.admin:
        return HTMLResponse("<h3>Access Denied</h3>", status_code=403)

    # Fetch all employees under this admin's managers
    manager_ids = [
    mid for (mid,) in db.query(User.id)
                      .filter(
                          User.created_by == current_user.id,
                          User.role == UserRole.manager,
                          User.is_active == True
                      ).all()
]
    if not manager_ids:
        employees = []
    else:
        employees = (
        db.query(User)
          .filter(
              User.role == UserRole.employee,
              User.is_active == True,
              User.created_by.in_(manager_ids)
          )
          .order_by(asc(User.username))
          .all())

    data = []
    for emp in employees:
        manager = db.query(User).filter(User.id == emp.created_by, User.role == UserRole.manager).first()
        t = db.query(Task).filter(Task.assigned_to == emp.id).count()
        manager_name = manager.username if manager else "N/A"
        data.append({
            "uuid": str(emp.id),
            "username": emp.username,
            "email": emp.email,
            "full_name": emp.full_name,
            "role": "employee",
            "manager_id": str(emp.created_by),
            "manager_name": manager_name,
            "is_active": emp.is_active,
            "task_count": t,
        })

    # Render the employees template
    return templates.TemplateResponse(
        "admin/employees.html",
        {"request": request, "employees": data, "current_user": current_user}
    )

@router.get("/tasks", response_class=HTMLResponse)
def tasks(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # validate token
): 
    # ✅ ensure only admin can access
    if current_user.role != UserRole.admin:
        return HTMLResponse("<h3>Access Denied</h3>", status_code=403)

    # Fetch all tasks created by this admin or their managers
    manager_ids = [
        mid for (mid,) in db.query(User.id)
                          .filter(
                              User.created_by == current_user.id,
                              User.role == UserRole.manager,
                              User.is_active == True
                          ).all()
    ]
    if not manager_ids:
        tasks = []
    else:
        tasks = (
            db.query(Task)
              .filter(
                  Task.created_by.in_(manager_ids)
              )
              .order_by(desc(Task.created_at))
              .all()
        )

    ts_map ={
            ts.pending: "pending",
            ts.in_progress: "in progress",
            ts.completed: "completed"
        }
    data = []
    for t in tasks:
        creator = db.query(User).filter(User.id == t.created_by).first()
        assignee = db.query(User).filter(User.id == t.assigned_to).first()
        creator_name = creator.username if creator else "N/A"
        assignee_name = assignee.username if assignee else "Unassigned"
        data.append({
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": ts_map[t.status],
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_at": t.created_at.isoformat(),
            "created_by_id": str(t.created_by),
            "created_by_name": creator_name,
            "assigned_to_id": str(t.assigned_to) if t.assigned_to else None,
            "assigned_to_name": assignee_name,
        })

    # Render the tasks template
    return templates.TemplateResponse(
        "admin/tasks.html",
        {"request": request, "tasks": data, "current_user": current_user}
    )