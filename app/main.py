from fastapi import FastAPI
from routers import auth, manager, tasks,admin, employee

app = FastAPI(title="Task Management System API")

# include routers
app.include_router(auth.router)
app.include_router(manager.router)
app.include_router(admin.router)
app.include_router(employee.router)
app.include_router(tasks.manager_tasks_router)
app.include_router(tasks.employee_tasks_router)

@app.get("/")
def root():
    return {"message": "API is running!"}
