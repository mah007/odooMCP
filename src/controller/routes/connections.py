"""Odoo connection management routes."""

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.controller.auth import require_auth
from src.controller.crypto import decrypt_credential, encrypt_credential
from src.mcp.odoo_client import ConnectionConfig, OdooClient
from src.mcp.transport.base import OdooError
from src.mcp.transport.detect import detect_version, select_mode
from src.shared.database import get_db
from src.shared.models import OdooConnection

router = APIRouter(prefix="/api/connections", tags=["connections"])

ApiMode = Literal["auto", "xmlrpc", "json2"]
MODE_LABEL = {"json2": "JSON-2", "xmlrpc": "XML-RPC"}


class ConnectionCreate(BaseModel):
    name: str
    url: str
    database: str
    username: str
    credential: str
    credential_type: Literal["api_key", "password"] = "api_key"
    api_mode: ApiMode = "auto"
    verify_ssl: bool = True
    timeout: int = Field(120, ge=5, le=900)
    default_context: dict[str, Any] | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    database: str | None = None
    username: str | None = None
    credential: str | None = None
    credential_type: Literal["api_key", "password"] | None = None
    api_mode: ApiMode | None = None
    verify_ssl: bool | None = None
    timeout: int | None = Field(None, ge=5, le=900)
    # {} clears it
    default_context: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


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
        "api_mode": conn.api_mode or "auto",
        "verify_ssl": bool(conn.verify_ssl),
        "timeout": conn.timeout or 120,
        "default_context": _loads(conn.default_context, {}),
        "detected_version": conn.detected_version,
        "detected_mode": conn.detected_mode,
        "last_test_steps": _loads(conn.last_test_steps, []),
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
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
        api_mode=body.api_mode,
        verify_ssl=body.verify_ssl,
        timeout=body.timeout,
        default_context=json.dumps(body.default_context, ensure_ascii=False) if body.default_context else None,
        updated_at=_now(),
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
    if body.credential:
        conn.credential = encrypt_credential(body.credential)
    if body.credential_type is not None:
        conn.credential_type = body.credential_type
    if body.api_mode is not None:
        conn.api_mode = body.api_mode
    if body.verify_ssl is not None:
        conn.verify_ssl = body.verify_ssl
    if body.timeout is not None:
        conn.timeout = body.timeout
    if body.default_context is not None:
        conn.default_context = json.dumps(body.default_context, ensure_ascii=False) if body.default_context else None
    conn.status = "untested"
    conn.updated_at = _now()
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


def run_connection_test(conn: OdooConnection) -> tuple[list[dict], str | None, str | None, str | None]:
    """Detect → choose transport → authenticate → read the user.

    Returns (steps, detected_version, detected_mode, error summary or None).
    """
    steps: list[dict] = []
    trail: list[str] = []
    version = mode = None
    step = "detect version"
    client: OdooClient | None = None
    try:
        info = detect_version(conn.url, verify_ssl=bool(conn.verify_ssl))
        version = info.raw
        steps.append({"step": step, "ok": True, "detail": f"Odoo {info.raw}"})
        trail.append(f"detected {info.raw}")

        step = "choose transport"
        mode, note = select_mode(conn.api_mode or "auto", info, conn.credential_type)
        steps.append({"step": step, "ok": True, "detail": MODE_LABEL[mode] + (f" — {note}" if note else "")})
        trail.append(MODE_LABEL[mode])

        step = "authenticate"
        config = ConnectionConfig(
            id=conn.id, url=conn.url, database=conn.database, username=conn.username,
            secret=decrypt_credential(conn.credential), credential_type=conn.credential_type,
            api_mode=conn.api_mode or "auto", verify_ssl=bool(conn.verify_ssl), timeout=conn.timeout or 120,
        )
        client = OdooClient(config, version=info)
        uid = client.uid()
        steps.append({"step": step, "ok": True, "detail": f"user id {uid}"})

        step = "read user"
        user = client.call("res.users", "read", ids=[uid], kwargs={"fields": ["name", "login"]})[0]
        steps.append({"step": step, "ok": True, "detail": f"{user['name']} ({user['login']})"})
        return steps, version, mode, None
    except Exception as exc:  # noqa: BLE001 — report every failure in the UI
        if isinstance(exc, OdooError):
            status = f"{exc.status} " if exc.status else ""
            detail = f"{status}{exc.message}"
        else:
            detail = f"{type(exc).__name__}: {exc}"
        steps.append({"step": step, "ok": False, "detail": detail})
        return steps, version, mode, " → ".join(trail + [detail])
    finally:
        if client is not None:
            client.close()


@router.post("/{conn_id}/test")
def test_connection(
    conn_id: int, db: Session = Depends(get_db), _: str = Depends(require_auth)
):
    conn = db.get(OdooConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    steps, version, mode, error = run_connection_test(conn)
    conn.status = "error" if error else "ok"
    conn.last_error = error
    conn.last_test_steps = json.dumps(steps, ensure_ascii=False)
    if version:
        conn.detected_version = version
    if mode:
        conn.detected_mode = mode
    conn.last_tested_at = _now()
    conn.updated_at = _now()  # makes the MCP service rebuild its client (fresh detection)
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
    conn.updated_at = _now()
    db.commit()
    db.refresh(conn)
    return _serialize(conn)
