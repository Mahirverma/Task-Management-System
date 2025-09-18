from fastapi import FastAPI, APIRouter, Request, Depends
from typing import Optional
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import logging
from fastapi.staticfiles import StaticFiles
from app.routers import auth, manager, tasks, admin, employee
from app.db import Base, engine, get_db
from app.core.security import get_optional_user
from sqlalchemy.orm import Session
from app.models.user import User

app = FastAPI(title="Task Management System API")

templates = Jinja2Templates(directory="app/templates")

# Basic logging setup to help local debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

# include routers
app.include_router(auth.router)
app.include_router(manager.router)
app.include_router(admin.router)
app.include_router(employee.router)
app.include_router(tasks.manager_tasks_router)
app.include_router(tasks.employee_tasks_router)

# Serve static JS/CSS from templates folders so frontend assets are available
app.mount("/js", StaticFiles(directory="app/templates/js"), name="js")
app.mount("/css", StaticFiles(directory="app/templates/css"), name="css")

@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_optional_user)):
    return templates.TemplateResponse("index.html", {"request": request, "current_user": current_user})
