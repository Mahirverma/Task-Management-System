from fastapi import APIRouter

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)

@router.post("/login")
def login(data: dict):
    email = data.get("email")
    password = data.get("password")
    # temporary response (later add JWT + validation)
    return {"message": "Login successful", "data": {"email": email}}