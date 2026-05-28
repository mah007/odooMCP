"""API key management routes."""

import secrets

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.controller.auth import require_auth
from src.shared.database import get_db
from src.shared.models import ApiKey

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str


def _serialize(key: ApiKey, full_key: str | None = None) -> dict:
    data = {
        "id": key.id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "request_count": key.request_count,
    }
    if full_key is not None:
        data["key"] = full_key
    return data


@router.get("")
def list_keys(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    rows = db.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars().all()
    return [_serialize(k) for k in rows]


@router.post("")
def create_key(body: ApiKeyCreate, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    raw_key = secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    api_key = ApiKey(
        name=body.name,
        key_hash=key_hash,
        key_prefix=raw_key[:8],
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    # Return full key once — it is never stored in plaintext
    return _serialize(api_key, full_key=raw_key)


@router.delete("/{key_id}", status_code=204)
def revoke_key(key_id: int, db: Session = Depends(get_db), _: str = Depends(require_auth)):
    key = db.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    key.is_active = False
    db.commit()
