from fastapi import FastAPI
from routers import auth  

app = FastAPI(title="Task Management System API")

# include routers
app.include_router(auth.router)

@app.get("/")
def root():
    return {"message": "API is running!"}
