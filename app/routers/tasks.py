from fastapi import APIRouter, Path, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.orm import Session
from db import get_db
from models.user import User, UserRole
from models.task import Task, TaskStatus
from models.task_log import TaskLog
from models.task_log import TaskStatus as log
from schemas.task import TaskCreate
from core.security import get_current_user
from utils.validators import validate_uuid
from datetime import datetime, date
import uuid


# Manager task routes
manager_tasks_router = APIRouter(
    prefix="/manager/{manager_id}/tasks",
    tags=["Manager Tasks"]
)

employee_tasks_router = APIRouter(
    prefix="/employee/{employee_id}/tasks",
    tags=["Employee Tasks"]
)

# ----------------- Endpoints -----------------

# -------- Manager's Task API -----------------
@manager_tasks_router.post("")
def create_task(
    payload: TaskCreate,
    manager_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not payload:
        raise HTTPException(status_code=400, detail="Request body must contain payload")

    title = payload.title
    description = payload.description
    assigned_to = payload.assigned_to
    due_date = payload.due_date
    if not title or not description:
        raise HTTPException(status_code=400, detail="Title and description required")
    if len(title) > 255:
        raise HTTPException(status_code=400, detail="Title too long")

    assigned_uuid = validate_uuid(assigned_to)
    employee = db.query(User).filter(
    User.id == assigned_uuid,
    User.role == UserRole.employee,
    User.created_by == manager_uuid,
    User.is_active == True
        ).first()

    if not employee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only assign task to your employees"
        )

    task = Task(
        title=title,
        description=description,
        status="pending",
        assigned_to=assigned_uuid,
        start_date = datetime.now(),
        due_date = due_date,
        created_by=manager_uuid,
        created_at=datetime.now()
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
        raise HTTPException(status_code=500, detail=str(e))

    # Optional: invalidate Redis cache
    # _invalidate_manager_cache(manager_uuid)
    resp={
        "message": "Task created successfully",
        "data": {
            "uuid": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "start_date":str(task.start_date),
            "due_date": str(task.due_date),
            "assigned_to": str(task.assigned_to),
            "created_by": str(task.created_by),
        }
    }

    return JSONResponse(status_code=201, content=resp)


@manager_tasks_router.patch("/{task_id}")
def update_task(
    manager_id: str = Path(...),
    task_id: str = Path(...),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)
    task_uuid = validate_uuid(task_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload:
        raise HTTPException(status_code=400, detail="Request body must contain payload")

    new_assigned = payload.get("assigned_to")
    new_title = payload.get("title","")
    new_description = payload.get("description","")

    task = db.query(Task).filter(Task.id == task_uuid).with_for_update().first()
    if not task or task.created_by != manager_uuid:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.completed:
        raise HTTPException(status_code=400, detail="Completed task cannot be updated")

    if new_assigned:
        assigned_uuid = validate_uuid(new_assigned)
        if assigned_uuid != task.assigned_to:
            employee = db.query(User).filter(
                        User.id == assigned_uuid,
                        User.role == UserRole.employee,
                        User.created_by == manager_uuid,
                        User.is_active == True
                        ).first()
            if not employee:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only assign task to your employees"
                )
            task.assigned_to = assigned_uuid
            task.status = TaskStatus.pending
    
    if new_title:
        task.title = new_title
    
    if new_description:
        task.description = new_description


    # Log task update
    log_status_map = {
        TaskStatus.pending: log.pending,
        TaskStatus.in_progress:  log.in_progress,
        TaskStatus.completed:  log.completed
    }
    try:
        db.add(task)
        db.flush()
        task_log = TaskLog(task_id=task.id, status=log_status_map[task.status], created_at=datetime.now())
        db.add(task_log)
        db.commit()
        # db.refresh(task)
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Database busy, try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # _invalidate_manager_cache(manager_uuid)

    return JSONResponse(status_code=200, content={
        "message": "Task status updated successfully",
        "data": {
            "uuid": str(task.id),
            "status": task.status.value,
            "assigned_to": str(task.assigned_to),
            "title": str(task.title),
            "dscription": str(task.description)
        }
    })

@manager_tasks_router.get("")
def list_manager_tasks(
    manager_id: str = Path(...),
    limit: int = Query(40, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    manager_uuid = validate_uuid(manager_id)

    if current_user.id != manager_uuid or current_user.role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Not authorized")

    if limit > 100:
        raise HTTPException(status_code=400, detail="limit exceeds maximum of 100")

    tasks = db.query(Task).filter(Task.created_by == manager_uuid).order_by(Task.created_at.desc()).limit(limit).offset(offset).all()

    data = [
        {
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": t.status.value,
            "assigned_to": str(t.assigned_to),
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]

    return JSONResponse(status_code=200, content={
        "message": "Tasks fetched successfully",
        "data": data
    })


@manager_tasks_router.get("/{task_id}")
def get_task(
    task_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task_uuid = validate_uuid(task_id)

    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only manager or assigned employee can view
    if current_user.role == UserRole.manager and current_user.id != task.created_by:
        raise HTTPException(status_code=403, detail="Not authorized")

    return JSONResponse(status_code=200, content={
        "message": "Task fetched successfully",
        "data": {
            "uuid": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "assigned_to": str(task.assigned_to),
            "created_by": str(task.created_by),
        }
    })

@manager_tasks_router.delete("/{task_id}")
def delete_task(
    task_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task_uuid = validate_uuid(task_id)

    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only manager or assigned employee can delete
    if current_user.role == UserRole.manager and current_user.id == task.created_by:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        db.delete(task)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # _invalidate_manager_cache(manager_uuid)

    return JSONResponse(status_code=200, content={
        "message": "Task deleted successfully",
        "data": {"uuid": str(task.id)}
    })


# -------- Employee's Task API -----------------


@employee_tasks_router.patch("/{task_id}")
def update_task(
    employee_id: str = Path(...),
    task_id: str = Path(...),
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)
    task_uuid = validate_uuid(task_id)

    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload:
        raise HTTPException(status_code=400, detail="Request body must contain payload")

    try:
        status = payload["status"]
    except:
        raise HTTPException(status_code=403, detail="Not authorized")

    employee = db.query(User).filter(User.id == employee_id, User.role == UserRole.employee).first()
    manager_uuid = employee.created_by
    task = db.query(Task).filter(Task.id == task_uuid).with_for_update().first()
    if not task or task.created_by != manager_uuid:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == TaskStatus.completed:
        raise HTTPException(status_code=400, detail="Completed task cannot be updated")

    # Log task update
    log_status_map = {
        TaskStatus.pending: log.pending,
        TaskStatus.in_progress:  log.in_progress,
        TaskStatus.completed:  log.completed
    }
    status_map = {
        "pending":TaskStatus.pending,
        "in-progress":TaskStatus.in_progress,
        "in progress":TaskStatus.in_progress,
        "in_progress":TaskStatus.in_progress,
        "completed":TaskStatus.completed
    }

    task.status = status_map[status]
    try:
        db.add(task)
        db.flush()
        task_log = TaskLog(task_id=task.id, status=log_status_map[task.status], created_at=datetime.now())
        db.add(task_log)
        db.commit()
        # db.refresh(task)
    except OperationalError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Database busy, try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # _invalidate_manager_cache(manager_uuid)

    return JSONResponse(status_code=200, content={
        "message": "Task status updated successfully",
        "data": {
            "uuid": str(task.id),
            "status": task.status.value,
            "assigned_to": str(task.assigned_to),
            "title": str(task.title),
            "dscription": str(task.description)
        }
    })


@employee_tasks_router.get("/{task_id}")
def get_task(
    task_id: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task_uuid = validate_uuid(task_id)

    task = db.query(Task).filter(Task.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only manager or assigned employee can view
    if current_user.role == UserRole.employee and current_user.id != task.assigned_to:
        raise HTTPException(status_code=403, detail="Not authorized")

    return JSONResponse(status_code=200, content={
        "message": "Task fetched successfully",
        "data": {
            "uuid": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "assigned_to": str(task.assigned_to),
            "created_by": str(task.created_by),
        }
    })

@employee_tasks_router.get("")
def list_employee_tasks(
    employee_id: str = Path(...),
    limit: int = Query(40, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    employee_uuid = validate_uuid(employee_id)

    if current_user.id != employee_uuid or current_user.role != UserRole.employee:
        raise HTTPException(status_code=403, detail="Not authorized")

    if limit > 100:
        raise HTTPException(status_code=400, detail="limit exceeds maximum of 100")

    tasks = db.query(Task).filter(Task.assigned_to == employee_uuid).order_by(Task.created_at.desc()).limit(limit).offset(offset).all()

    data = [
        {
            "uuid": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": t.status.value,
            "assigned_to": str(t.assigned_to),
            "start_date": t.start_date.isoformat() if t.start_date else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]

    return JSONResponse(status_code=200, content={
        "message": "Tasks fetched successfully",
        "data": data
    })