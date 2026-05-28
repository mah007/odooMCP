"""Odoo connection management routes."""

import ssl
import xmlrpc.client
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.controller.auth import require_auth
from src.controller.crypto import decrypt_credential, encrypt_credential
from src.shared.database import get_db
from src.shared.models import OdooConnection

router = APIRouter(prefix="/api/connections", tags=["connections"])


class ConnectionCreate(BaseModel):
    name: str
    url: str
    database: str
    username: str
    credential: str
    credential_type: Literal["api_key", "password"] = "api_key"


class ConnectionUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    database: str | None = None
    username: str | None = None
    credential: str | None = None
    credential_type: Literal["api_key", "password"] | None = None


def _serialize(conn: OdooConnection) -> dict:
    return {
        "id": conn.id,
        "name": conn.name,
        "url": conn.url,
        "database": conn.database,
        "username": conn.username,
        "credential_type": conn.credential_type,
        "is_active": conn.is_active,
        "status": conn.status,
        "last_tested_at": conn.last_tested_at.isoformat() if conn.last_tested_at else None,
        "last_error": conn.last_error,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
    }


@router.get("")
def list_connections(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    rows = db.execute(select(OdooConnection).order_by(OdooConnection.created_at)).scalars().all()
    return [_serialize(r) for r in rows]


@router.post("")
def create_connection(
    body: ConnectionCreate, db: Session = Depends(get_db), _: str = Depends(require_auth)
):
    conn = OdooConnection(
        name=body.name,
        url=body.url.rstrip("/"),
        database=body.database,
        username=body.username,
        credential=encrypt_credential(body.credential),
        credential_type=body.credential_type,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _serialize(conn)


@router.put("/{conn_id}")
def update_connection(
    conn_id: int,
    body: ConnectionUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(require_auth),
):
    conn = db.get(OdooConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if body.name is not None:
        conn.name = body.name
    if body.url is not None:
        conn.url = body.url.rstrip("/")
    if body.database is not None:
        conn.database = body.database
    if body.username is not None:
        conn.username = body.username
    if body.credential is not None:
        conn.credential = encrypt_credential(body.credential)
    if body.credential_type is not None:
        conn.credential_type = body.credential_type
    conn.status = "untested"
    db.commit()
    db.refresh(conn)
    return _serialize(conn)


@router.delete("/{conn_id}", status_code=204)
def delete_connection(
    conn_id: int, db: Session = Depends(get_db), _: str = Depends(require_auth)
):
    conn = db.get(OdooConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    db.delete(conn)
    db.commit()


@router.post("/{conn_id}/test")
def test_connection(
    conn_id: int, db: Session = Depends(get_db), _: str = Depends(require_auth)
):
    conn = db.get(OdooConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    credential = decrypt_credential(conn.credential)
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    common = xmlrpc.client.ServerProxy(
        urljoin(conn.url, "/xmlrpc/2/common"),
        context=ssl_ctx,
        allow_none=True,
    )
    now = datetime.now(timezone.utc)
    try:
        uid = common.authenticate(conn.database, conn.username, credential, {})
        if not uid:
            raise ValueError("Authentication returned no user ID — check credentials")
        conn.status = "ok"
        conn.last_error = None
    except Exception as exc:
        conn.status = "error"
        conn.last_error = str(exc)
    finally:
        conn.last_tested_at = now
        db.commit()
        db.refresh(conn)

    return _serialize(conn)


@router.post("/{conn_id}/activate")
def activate_connection(
    conn_id: int, db: Session = Depends(get_db), _: str = Depends(require_auth)
):
    conn = db.get(OdooConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Deactivate all others
    all_conns = db.execute(select(OdooConnection)).scalars().all()
    for c in all_conns:
        c.is_active = c.id == conn_id
    db.commit()
    db.refresh(conn)
    return _serialize(conn)
