"""Auth routes: setup wizard + login."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.controller.auth import create_token, hash_password, verify_password
from src.shared.database import get_db
from src.shared.models import AdminUser

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/status")
def setup_status(db: Session = Depends(get_db)):
    """Return whether the system has been set up (any admin user exists)."""
    count = db.execute(select(AdminUser)).scalars().first()
    return {"setup_done": count is not None}


@router.post("/setup")
def setup(body: SetupRequest, db: Session = Depends(get_db)):
    """Create the first admin user. Only works when no users exist."""
    existing = db.execute(select(AdminUser)).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Setup already completed")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    user = AdminUser(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return {"token": create_token(body.username)}


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(
        select(AdminUser).where(AdminUser.username == body.username, AdminUser.is_active == True)  # noqa: E712
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(user.username)}
