"""Admin user management routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.controller.auth import hash_password, require_auth, verify_password
from src.shared.database import get_db
from src.shared.models import AdminUser

router = APIRouter(prefix="/api/admins", tags=["admins"])


def _serialize(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _current_user(username: str, db: Session) -> AdminUser:
    user = db.execute(
        select(AdminUser).where(AdminUser.username == username)
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Current user not found")
    return user


@router.get("")
def list_admins(db: Session = Depends(get_db), me: str = Depends(require_auth)):
    rows = db.execute(select(AdminUser).order_by(AdminUser.created_at)).scalars().all()
    return [_serialize(r) for r in rows]


class AdminCreate(BaseModel):
    username: str
    password: str


@router.post("", status_code=201)
def create_admin(body: AdminCreate, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    existing = db.execute(
        select(AdminUser).where(AdminUser.username == body.username)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = AdminUser(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.delete("/{admin_id}", status_code=204)
def delete_admin(admin_id: int, db: Session = Depends(get_db), me: str = Depends(require_auth)):
    target = db.get(AdminUser, admin_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Admin not found")
    if target.username == me:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    db.delete(target)
    db.commit()


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.put("/me/password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    me: str = Depends(require_auth),
):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters")
    user = _current_user(me, db)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated"}
