# app/routers/manager.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import EmailStr, BaseModel
# import uuid
from datetime import datetime

from sqlalchemy import func, desc
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from passlib.context import CryptContext

# from core.config import settings
from app.db import get_db
from app.models.user import User, UserRole
from app.models.task import Task, TaskStatus
from app.models.task_log import TaskLog, TaskStatus as log
from app.models.time_log import TimeLog
from app.core.security import hash_password,verify_password, get_current_user
from app.utils.email_utils import send_email
from app.utils.validators import validate_uuid

# Optional Redis (for cache invalidation). If not configured, functions will be no-ops.
# try:
#     import redis
#     _redis_client = redis.from_url(settings.redis_url) if getattr(settings, "redis_url", None) else None
# except Exception:
#     _redis_client = None

router = APIRouter(prefix="/manager", tags=["Manager"])
templates = Jinja2Templates(directory="app/templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
import logging
logger = logging.getLogger(__name__)


@router.get("/dashboard", response_class=HTMLResponse)
def manager_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Render manager dashboard using current_user; fetch employees and tasks overview
    employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee).order_by(User.username).all()
    tasks = db.query(Task).filter(Task.created_by == current_user.id).order_by(Task.created_at.desc()).limit(50).all()

    employees_data = []
    for e in employees:
        tcount = db.query(Task).filter(Task.assigned_to == e.id).count()
        employees_data.append({
            "id": e.id,
            "uuid": str(e.id),
            "username": e.username,
            "email": e.email,
            "full_name": e.full_name,
            "task_count": tcount,
            "manager_id": e.created_by,
            "is_active": e.is_active,
        })

    tasks_data = []
    for t in tasks:
        assigned_user = None
        if t.assigned_to:
            assigned_user = db.query(User).filter(User.id == t.assigned_to).first()
        assigned_to_name = assigned_user.username if assigned_user else None
        creator = db.query(User).filter(User.id == t.created_by).first()
        created_by_name = creator.username if creator else None
        status_map = {
            TaskStatus.pending: "pending",
            TaskStatus.in_progress: "in progress",
            TaskStatus.completed: "completed"
        }
        tasks_data.append({
            "id": t.id,
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": status_map[t.status],
            "assigned_to_name": assigned_to_name,
            "created_by_id": t.created_by,
            "created_by_name": created_by_name,
        })

    return templates.TemplateResponse(
        "manager/dashboard.html",
        {"request": request, "current_user": current_user, "employees": employees_data, "tasks": tasks_data},
    )

@router.get("/employees/new", response_class=HTMLResponse)
def new_employee_form_noid(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # helper route that uses the authenticated manager as manager_id
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user})


@router.get("/employees/{employee_id}", summary="Get employee details (no manager id)", response_class=HTMLResponse)
def get_employee_noid(request: Request, employee_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # allow manager or admin to view employee page via short URL
    employee_uuid = validate_uuid(employee_id)
    employee = db.query(User).filter(User.id == employee_uuid, User.role == UserRole.employee).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if current_user.role == UserRole.manager and employee.created_by != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # fetch tasks
    tasks = db.query(Task).filter(Task.assigned_to == employee_uuid).order_by(Task.created_at.desc()).all()
    tasks_data = []
    for t in tasks:
        assigned_user = None
        if t.assigned_to:
            assigned_user = db.query(User).filter(User.id == t.assigned_to).first()
        assigned_to_name = assigned_user.username if assigned_user else None
        status_map = {
            TaskStatus.pending: "pending",
            TaskStatus.in_progress: "in progress",
            TaskStatus.completed: "completed"
        }
        tasks_data.append({
            "id": t.id,
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": status_map[t.status],
            "due_date": t.due_date.isoformat() if getattr(t, 'due_date', None) else None,
            "assigned_to_name": assigned_to_name,
        })

    # attempt to load TimeLog model dynamically (support variations in naming/field layout)
    time_logs_data = []
    try:
        time_logs = db.query(TimeLog).filter(TimeLog.user_id == employee_uuid).order_by(TimeLog.created_at.desc()).all()
        for tl in time_logs:
            task_id_val = tl.task_id
            if task_id_val:
                task_row = db.query(Task).filter(Task.id == task_id_val).first()

            time_logs_data.append({
                "id": tl.id,
                "uuid": str(tl.id),
                "user_id": tl.user_id,
                "task": task_row.title,
                "date": tl.date,
                "duration": tl.hours,
                "notes": tl.notes,
                "created_at": tl.created_at,
            })
    except Exception:
        # don't fail the whole request if time logs can't be fetched
        time_logs_data = []

    return templates.TemplateResponse(
        "manager/employee_detail.html",
        {
            "request": request,
            "employee": employee,
            "tasks": tasks_data,
            "time_logs": time_logs_data,
            "current_user": current_user,
            "role": current_user.role.value
        }
    )

@router.get("/tasks/new", response_class=HTMLResponse)
def new_task_form_noid(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee, User.is_active == True).all()
    return templates.TemplateResponse("manager/create_task.html", {"request": request, "current_user": current_user, "employees": employees})


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def get_task_noid(request: Request, task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_uuid = validate_uuid(task_id)
    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    status_map = {
        TaskStatus.pending: "pending",
        TaskStatus.in_progress: "in progress",
        TaskStatus.completed: "completed"
    }
    task.status = status_map[task.status]

    # Authorization: manager who created the task or assigned employee or admin
    if current_user.role == UserRole.manager and current_user.id != task.created_by and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    assigned_user = None
    if task.assigned_to:
        assigned_user = db.query(User).filter(User.id == task.assigned_to).first()
    assigned_to_name = assigned_user.username if assigned_user else None
    return templates.TemplateResponse("task_detail.html", {"request": request, "task": task, "assigned_to_name": assigned_to_name, "current_user": current_user})


@router.get("/{manager_id}/profile", response_class=HTMLResponse)
def manager_profile(request: Request, manager_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    manager_uuid = validate_uuid(manager_id)
    if current_user.id != manager_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this profile")

    user = db.query(User).filter(User.id == manager_uuid).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

    return templates.TemplateResponse("manager/profile.html", {"request": request, "current_user": current_user, "user": user})

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

@router.post("/{manager_id}/profile", summary="Update manager profile")
def update_manager_profile(
    manager_id: str = Path(..., description="Manager UUID"),
    username: str = Form(None),
    email: str = Form(None),
    full_name: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)

    # only the manager themselves may update their profile via the HTML form
    if current_user.id != manager_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another manager's profile")

    if not any([username, email, full_name]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field (username, email or full_name) is required")

    try:
        manager_row = db.query(User).filter(User.id == manager_uuid).with_for_update().first()
        if not manager_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

        if email:
            email_val = email.strip()
            class TempEmailModel(BaseModel):
                email: EmailStr
            try:
                TempEmailModel(email=email_val)
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")

            # ensure no other user has this email
            existing = db.query(User).filter(func.lower(User.email) == email_val.lower(), User.id != manager_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")

            manager_row.email = email_val.lower()

        if username:
            username_val = username.strip()
            existing = db.query(User).filter(func.lower(User.username) == username_val.lower(), User.id != manager_uuid).first()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already in use")
            manager_row.username = username_val

        if full_name is not None:
            manager_row.full_name = full_name.strip() if full_name else None

        db.add(manager_row)
        db.commit()
        db.refresh(manager_row)

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
    return RedirectResponse(url=f"/manager/dashboard", status_code=303)


@router.post("/{manager_id}/employees", summary="Create a new employee under manager")
async def create_employee(
    request: Request,
    manager_id: str = Path(..., description="Manager UUID"),
    username: str = Form(None),
    email: str = Form(None),
    password: str = Form(None),
    full_name: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the manager can create their employees")

    # Support both JSON API clients and browser form submissions
    payload = None
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except Exception:
            payload = None

    if payload:
        username = payload.get("username")
        email = payload.get("email")
        password = payload.get("password")
        full_name = payload.get("full_name", "")

    # For form submissions ensure required fields present
    if not username or not email or not password:
        # For API calls return JSON error, for browser forms re-render create page
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="username, email and password are required")
        employees = None
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": "username, email and password are required"})

    class TempEmailModel(BaseModel):
        email: EmailStr
    try:
        TempEmailModel(email=email)
    except Exception:
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email format")
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": "Invalid email format"})

    existing = db.query(User).filter((func.lower(User.email) == email.lower()) | (func.lower(User.username) == username.lower())).first()
    if existing:
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists")
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": "Email or username already exists"})

    from core.security import hash_password
    new_user = User(
        username=username.strip(),
        email=email.strip().lower(),
        full_name=(full_name.strip() if full_name else None),
        role=UserRole.employee,
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
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict creating employee")
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": "Conflict creating employee"})
    except Exception as e:
        db.rollback()
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": str(e)})

    # On browser form submission redirect back to dashboard
    if not content_type.startswith("application/json"):
        return RedirectResponse(url=f"/manager/dashboard", status_code=303)

    resp = {
        "message": "Employee created successfully",
        "data": {
            "uuid": str(new_user.id),
            "username": new_user.username,
            "email": new_user.email,
            "full_name": new_user.full_name,
            "role": "employee",
            "created_by": str(new_user.created_by),
        },
    }
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp)


@router.post("/{manager_id}/tasks", summary="Create a new task under manager")
async def create_task_from_form(
    request: Request,
    manager_id: str = Path(..., description="Manager UUID"),
    title: str = Form(None),
    description: str = Form(None),
    assigned_to: str = Form(None),
    due_date: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # support both JSON payloads and form posts
    content_type = request.headers.get("content-type", "")
    payload = None
    if content_type.startswith("application/json"):
        try:
            payload = await request.json()
        except Exception:
            payload = None

    if payload:
        title = payload.get("title")
        description = payload.get("description")
        assigned_to = payload.get("assigned_to")
        due_date = payload.get("due_date")

    if not title or not description:
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title and description required")
        employees = db.query(User).filter(User.created_by == manager_uuid, User.role == UserRole.employee, User.is_active == True).all()
        return templates.TemplateResponse("manager/create_task.html", {"request": request, "current_user": current_user, "employees": employees, "error": "Title and description required"})

    assigned_uuid = None
    if assigned_to:
        assigned_to_val = assigned_to.strip()
        if assigned_to_val:
            try:
                assigned_uuid = validate_uuid(assigned_to_val)
            except HTTPException:
                employees = db.query(User).filter(User.created_by == manager_uuid, User.role == UserRole.employee, User.is_active == True).all()
                if content_type.startswith("application/json"):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid employee selection")
                return templates.TemplateResponse("manager/create_task.html", {"request": request, "current_user": current_user, "employees": employees, "error": "Invalid employee selection"})

    if assigned_uuid:
        employee = db.query(User).filter(User.id == assigned_uuid, User.role == UserRole.employee, User.created_by == manager_uuid, User.is_active == True).first()
        if not employee:
            employees = db.query(User).filter(User.created_by == manager_uuid, User.role == UserRole.employee, User.is_active == True).all()
            if content_type.startswith("application/json"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only assign task to your employees")
            return templates.TemplateResponse("manager/create_task.html", {"request": request, "current_user": current_user, "employees": employees, "error": "Can only assign task to your employees"})

    from models.task import Task
    from models.task_log import TaskLog
    from datetime import datetime
    task = Task(
        title=title.strip(),
        description=description.strip(),
        status="pending",
        assigned_to=assigned_uuid,
        start_date=datetime.now(),
        due_date=(due_date if due_date else None),
        created_by=manager_uuid,
    )
    try:
        db.add(task)
        db.flush()
        task_log = TaskLog(task_id=task.id, status=task.status, created_at=datetime.now())
        db.add(task_log)
        db.commit()
        db.refresh(task)
    except Exception as e:
        db.rollback()
        employees = db.query(User).filter(User.created_by == manager_uuid, User.role == UserRole.employee, User.is_active == True).all()
        if content_type.startswith("application/json"):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
        return templates.TemplateResponse("manager/create_task.html", {"request": request, "current_user": current_user, "employees": employees, "error": str(e)})

    if not content_type.startswith("application/json"):
        return RedirectResponse(url=f"/manager/dashboard", status_code=303)

    resp = {
        "message": "Task created successfully",
        "data": {
            "uuid": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "assigned_to": str(task.assigned_to),
            "created_by": str(task.created_by),
        }
    }
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=resp)


@router.get("/{manager_id}/employees")
def list_employees(
    manager_id: str = Path(..., description="Manager UUID"),
    limit: int = Query(40, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)

    if limit > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="limit exceeds maximum of 100")

    if current_user.id != manager_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view these employees")

    employees = db.query(User).filter(
        User.created_by == manager_uuid,
        User.role == UserRole.employee,
        User.is_active == True
    ).order_by(User.username).limit(limit).offset(offset).all()

    resp = {
        "message": "Employees fetched successfully",
        "data": [
            {
                "uuid": str(e.id),
                "username": e.username,
                "email": e.email,
                "full_name": e.full_name,
                "role": "employee",
            } for e in employees
        ],
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.get("/{manager_id}/employees/{employee_id}", summary="Get employee details under manager", response_class=HTMLResponse)
def get_employee(
    request: Request,
    manager_id: str = Path(...),
    employee_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    employee_uuid = validate_uuid(employee_id)

    if current_user.role == UserRole.manager and current_user.id != manager_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    employee = db.query(User).filter(User.id == employee_uuid, User.role == UserRole.employee).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    employee.role = "Employee"

    if employee.created_by != manager_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee does not belong to this manager")

    # fetch tasks assigned to this employee
    tasks = db.query(Task).filter(Task.assigned_to == employee_uuid).order_by(Task.created_at.desc()).all()
    tasks_data = []
    for t in tasks:
        assigned_user = None
        if t.assigned_to:
            assigned_user = db.query(User).filter(User.id == t.assigned_to).first()
        assigned_to_name = assigned_user.username if assigned_user else None
        tasks_data.append({
            "id": t.id,
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "due_date": t.due_date.isoformat() if getattr(t, 'due_date', None) else None,
            "assigned_to_name": assigned_to_name,
        })
    return templates.TemplateResponse(
        "manager/employee_detail.html",
        {
            "request": request,
            "employee": employee,
            "tasks": tasks_data,
            "current_user": current_user
        }
    )


@router.get("/employees/{employee_id}", summary="Get employee details (no manager id)", response_class=HTMLResponse)
def get_employee_noid(request: Request, employee_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # allow manager or admin to view employee page via short URL
    employee_uuid = validate_uuid(employee_id)
    employee = db.query(User).filter(User.id == employee_uuid, User.role == UserRole.employee).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if current_user.role == UserRole.manager and employee.created_by != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    tasks = db.query(Task).filter(Task.assigned_to == employee_uuid).order_by(Task.created_at.desc()).all()
    return templates.TemplateResponse("manager/employee_detail.html", {"request": request, "employee": employee, "tasks": tasks, "current_user": current_user})




@router.post("/employees/create-form", response_class=HTMLResponse)
def create_employee_form_noid(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), full_name: str = Form(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Same as create_employee_form but uses authenticated manager id
    if current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    from core.security import hash_password
    if not username or not email or not password:
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": "username, email and password are required"})

    new_user = User(
        username=username.strip(),
        email=email.strip().lower(),
        full_name=(full_name.strip() if full_name else None),
        role=UserRole.employee,
        password_hash=hash_password(password),
        is_active=True,
        created_by=current_user.id,
    )
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("manager/create_employee.html", {"request": request, "current_user": current_user, "error": str(e)})

    return RedirectResponse(url=f"/manager/dashboard", status_code=303)


@router.post("/{manager_id}/reset_password")
def reset_manager_password(
    manager_id: str = Path(...),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
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
        manager_row = db.query(User).filter(User.id == manager_uuid).with_for_update().first()
        if not manager_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")

        manager_row.password_hash = hash_password(new_password)
        db.add(manager_row)
        db.commit()
        db.refresh(manager_row)
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Database busy")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not reset password")

    # Invalidate caches and (optionally) revoke tokens via token_version bump (not implemented here)
    # _invalidate_manager_cache(manager_uuid)

    resp = {"message": "Password updated successfully. Login again.", "data": {"uuid": str(manager_uuid)}}
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.patch("/{manager_id}/users/{employee_id}/deactivate")
def deactivate_employee(
    manager_id: str = Path(...),
    employee_id: str = Path(...),
    # payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if manager_uuid == employee_uuid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate self")

    employee = db.query(User).filter(User.id == employee_uuid, User.role == UserRole.employee).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if employee.created_by != manager_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee not under this manager")

    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee already inactive")

    try:
        employee.is_active = False
        db.add(employee)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to deactivate employee")

    # _invalidate_manager_cache(manager_uuid)

    resp = {
        "message": "Employee deactivated successfully",
        "data": {"uuid": str(employee_uuid), "is_active": False},
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)

@router.patch("/{manager_id}/users/{employee_id}/activate")
def activate_employee(
    manager_id: str = Path(...),
    employee_id: str = Path(...),
    # payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if manager_uuid == employee_uuid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot activate self")

    employee = db.query(User).filter(User.id == employee_uuid, User.role == UserRole.employee).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    if employee.created_by != manager_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee not under this manager")

    if employee.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee already active")

    try:
        employee.is_active = True
        db.add(employee)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to activate employee")

    # _invalidate_manager_cache(manager_uuid)

    resp = {
        "message": "Employee activated successfully",
        "data": {"uuid": str(employee_uuid), "is_active": True},
    }
    return JSONResponse(status_code=status.HTTP_200_OK, content=resp)


@router.get("/{manager_id}/employees/view", response_class=HTMLResponse)
def view_employees_page(request: Request, manager_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    manager_uuid = validate_uuid(manager_id)
    if current_user.id != manager_uuid and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view these employees")

    employees = db.query(User).filter(
        User.created_by == manager_uuid,
        User.role == UserRole.employee,
        User.is_active == True
    ).order_by(User.username).all()

    data = []
    for e in employees:
        tcount = db.query(Task).filter(Task.assigned_to == e.id).count()
        data.append({
            "id": e.id,
            "uuid": str(e.id),
            "username": e.username,
            "email": e.email,
            "full_name": e.full_name,
            "task_count": tcount,
            "manager_id": e.created_by,
        })

    return templates.TemplateResponse("manager/employees.html", {"request": request, "current_user": current_user, "employees": data})

@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form_noid(request: Request, task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_uuid = validate_uuid(task_id)
    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if current_user.role != UserRole.manager or current_user.id != task.created_by:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this task")

    employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee, User.is_active == True).all()
    return templates.TemplateResponse("manager/edit_task.html", {"request": request, "current_user": current_user, "task": task, "employees": employees})

@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_noid(request: Request, task_id: str = Path(...), title: str = Form(None), description: str = Form(None), assigned_to: str = Form(None), due_date: str = Form(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_uuid = validate_uuid(task_id)
    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    if current_user.role != UserRole.manager or current_user.id != task.created_by:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to edit this task")

    if not title or not description:
        employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee, User.is_active == True).all()
        return templates.TemplateResponse("manager/edit_task.html", {"request": request, "current_user": current_user, "task": task, "employees": employees, "error": "Title and description required"})

    assigned_uuid = None
    if assigned_to:
        assigned_to_val = assigned_to.strip()
        if assigned_to_val:
            try:
                assigned_uuid = validate_uuid(assigned_to_val)
            except HTTPException:
                employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee, User.is_active == True).all()
                return templates.TemplateResponse("manager/edit_task.html", {"request": request, "current_user": current_user, "task": task, "employees": employees, "error": "Invalid employee selection"})

    if assigned_uuid:
        employee = db.query(User).filter(User.id == assigned_uuid, User.role == UserRole.employee, User.created_by == current_user.id, User.is_active == True).first()
        if not employee:
            employees = db.query(User).filter(User.created_by == current_user.id, User.role == UserRole.employee, User.is_active == True).all()
            return templates.TemplateResponse("manager/edit_task.html", {"request": request, "current_user": current_user, "task": task, "employees": employees, "error": "Can only assign task to your employees"})
    
    task.title = title.strip()
    task.description = description.strip()
    task.due_date = datetime.strptime(due_date, "%Y-%m-%d") if due_date else None
    task.assigned_to = assigned_uuid

    db.add(task)

    status_map = {
        TaskStatus.pending : "pending",
        TaskStatus.in_progress: "in progress",
        TaskStatus.completed: "completed" 
    }

    # Log the task edit
    log = TaskLog(
        task_id=task.id,
        status=status_map[task.status],
        created_at=datetime.now()
    )
    db.add(log)
    db.commit()

    return RedirectResponse(url="/manager/dashboard", status_code=303)