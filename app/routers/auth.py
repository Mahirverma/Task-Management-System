from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import logging
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

logger = logging.getLogger(__name__)


@router.post("/login")
async def login(request: Request, email: str = Form(None), password: str = Form(None), db: Session = Depends(get_db)):
    """Accept form (browser) and JSON (API) logins.

    - For browser (form) submissions: set cookie and RedirectResponse to role dashboard.
    - For JSON submissions: return JSON with access token.
    """
    is_json = "application/json" in (request.headers.get("content-type") or "")

    if is_json:
        try:
            payload = await request.json()
            login_data = LoginRequest(**payload)
            email = login_data.email
            password = login_data.password
        except Exception:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Invalid request payload"})
    else:
        # form login: ensure values present
        if not email or not password:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Missing credentials"})

    email = (email or "").strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        logger.warning("Failed login attempt for %s", email)
        if is_json:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Invalid credentials"})
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

    if not user.is_active:
        logger.warning("Inactive user attempted login: %s", email)
        if is_json:
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"message": "User inactive"})
        return templates.TemplateResponse("login.html", {"request": request, "error": "User inactive"})

    access_token = create_access_token({"sub": str(user.id)})
    # choose redirect target based on role
    if user.role == UserRole.admin:
        redirect_url = f"/admin/dashboard?token={access_token}"
    elif user.role == UserRole.manager:
        redirect_url = f"/manager/dashboard?token={access_token}"
    else:
        redirect_url = f"/employee/dashboard?token={access_token}"

    logger.info("User %s logged in, redirecting to %s", email, redirect_url)

    if is_json:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Login successful", "data": {"access_token": access_token, "token_type": "bearer"}})

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response


@router.get("/logout")
def logout():
    # clear cookie and redirect to login page
    logger.info("Logout called; clearing access_token cookie")
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response
    # return {"message": "Login successful", "data": {"access_token": access_token, "token_type": "bearer"}}