from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from schemas.auth import LoginRequest, LoginResponse, TokenData
from core.security import verify_password, create_access_token
from models.user import User, UserRole  # SQLAlchemy user model
from db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

templates = Jinja2Templates(directory="templates")

@router.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
def login(request: Request,  email: str = Form(...),
    password: str = Form(...),db: Session = Depends(get_db)):

    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid credentials"}
        )
    
    if not user.is_active:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "User inactive"}
        )

    access_token = create_access_token({"sub": str(user.id)})
    if user.role == UserRole.admin:
        redirect_url = f"/admin/dashboard?token={access_token}"
    elif user.role == UserRole.manager:
        redirect_url = f"/manager/dashboard?token={access_token}"
    else:
        redirect_url = f"/employee/dashboard?token={access_token}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response
    # return {"message": "Login successful", "data": {"access_token": access_token, "token_type": "bearer"}}