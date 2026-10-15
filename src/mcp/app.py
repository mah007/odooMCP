"""FastAPI MCP service — port 8000. Auth, request log and client cache; protocol.py does the rest."""

import hashlib
import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import bcrypt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.controller.crypto import decrypt_credential
from src.mcp import protocol, shaping
from src.mcp.odoo_client import ConnectionConfig, OdooClient
from src.mcp.transport.base import OdooError
from src.shared.database import SessionLocal, init_db
from src.shared.models import ApiKey, OdooConnection, RequestLog

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("MCP service started")
    yield
    for _, client in _clients.values():
        client.close()
    logger.info("MCP service stopped")


app = FastAPI(title="Odoo MCP Service", lifespan=lifespan)
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["POST"],
        allow_headers=["*"], expose_headers=["Mcp-Session-Id"],
    )


# ── API keys ─────────────────────────────────────────────────────────────────

# sha256(raw key) → ApiKey.id, so bcrypt runs once per key and process, not on every request
_key_cache: dict[str, int] = {}


def _extract_key(request: Request) -> str:
    key = request.headers.get("X-API-Key", "").strip()
    if not key:
        auth = request.headers.get("Authorization", "")
        if auth[:7].lower() == "bearer ":
            key = auth[7:].strip()
    return key


def _validate_api_key(raw_key: str, db: Session) -> ApiKey | None:
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = _key_cache.get(digest)
    if key_id is not None:
        row = db.get(ApiKey, key_id)
        if row is not None and row.is_active:
            return row
        _key_cache.pop(digest, None)
    rows = db.execute(
        select(ApiKey).where(ApiKey.key_prefix == raw_key[:8], ApiKey.is_active == True)  # noqa: E712
    ).scalars().all()
    for row in rows:
        if bcrypt.checkpw(raw_key.encode(), row.key_hash.encode()):
            if len(_key_cache) > 1000:
                _key_cache.clear()
            _key_cache[digest] = row.id
            return row
    return None


# ── Odoo clients ─────────────────────────────────────────────────────────────

# connection id → (updated_at, client); rebuilt when the controller bumps updated_at
_clients: dict[int, tuple[datetime | None, OdooClient]] = {}
_clients_lock = threading.Lock()


def _config_from_row(conn: OdooConnection) -> ConnectionConfig:
    try:
        default_context = json.loads(conn.default_context) if conn.default_context else {}
    except ValueError:
        default_context = {}
    return ConnectionConfig(
        id=conn.id, url=conn.url, database=conn.database, username=conn.username,
        secret=decrypt_credential(conn.credential), credential_type=conn.credential_type,
        api_mode=conn.api_mode or "auto", verify_ssl=bool(conn.verify_ssl), timeout=conn.timeout or 120,
        default_context=default_context if isinstance(default_context, dict) else {},
    )


def get_client(conn: OdooConnection) -> OdooClient:
    with _clients_lock:
        cached = _clients.get(conn.id)
        if cached and cached[0] == conn.updated_at:
            return cached[1]
        # The replaced client is not closed: a request may still be using it; GC frees it.
        client = OdooClient(_config_from_row(conn))
        _clients[conn.id] = (conn.updated_at, client)
        return client


def _active_connection(db: Session) -> OdooConnection | None:
    return db.execute(
        select(OdooConnection).where(OdooConnection.is_active == True)  # noqa: E712
    ).scalars().first()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    db = SessionLocal()
    try:
        conn = _active_connection(db)
        return {"status": "ok", "version": protocol.SERVER_VERSION, "active_connection": conn.name if conn else None}
    finally:
        db.close()


@app.get("/mcp")
@app.delete("/mcp")
async def mcp_not_allowed():
    # No server-initiated SSE stream and no sessions to terminate.
    return Response(status_code=405, headers={"Allow": "POST"})


def _json(body, status: int = 200) -> Response:
    return Response(content=shaping.dumps(body).encode(), status_code=status, media_type="application/json")


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": f"Origin {origin} is not allowed"}, status_code=403)

    raw_key = _extract_key(request)
    db = SessionLocal()
    try:
        api_key_row = _validate_api_key(raw_key, db) if raw_key else None
        if api_key_row is None:
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)

        try:
            payload = json.loads(await request.body())
        except ValueError:
            return _json(protocol.parse_error(), 400)

        conn_holder: dict[str, OdooConnection | None] = {}
        tool_calls: list[protocol.ToolCallRecord] = []

        def client_factory() -> OdooClient:
            conn = _active_connection(db)
            conn_holder["conn"] = conn
            if conn is None:
                raise OdooError("NoActiveConnection", "No active Odoo connection is configured")
            return get_client(conn)

        rc = protocol.RequestContext(
            get_client=client_factory,
            scope=api_key_row.scope or "write",
            protocol_version=request.headers.get("MCP-Protocol-Version"),
            on_tool_call=tool_calls.append,
        )
        status, body = await protocol.handle_payload(payload, rc)

        if tool_calls:
            conn = conn_holder.get("conn")
            for rec in tool_calls:
                db.add(RequestLog(
                    tool_name=rec.tool, status=rec.status, duration_ms=rec.duration_ms,
                    connection_id=conn.id if conn else None, api_key_id=api_key_row.id,
                    error_message=rec.error[:2000] if rec.error else None,
                    response_bytes=rec.response_bytes, transport=rec.transport,
                ))
            db.execute(
                update(ApiKey).where(ApiKey.id == api_key_row.id).values(
                    request_count=ApiKey.request_count + len(tool_calls),
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            if conn is not None:
                _remember_detection(db, conn)
            db.commit()

        if body is None:
            return Response(status_code=202)
        return _json(body, status)
    finally:
        db.close()


def _remember_detection(db: Session, conn: OdooConnection) -> None:
    """Store the detected version/transport for the admin UI (does not bump updated_at)."""
    cached = _clients.get(conn.id)
    if not cached:
        return
    client = cached[1]
    version = client.known_version.raw if client.known_version else None
    mode = client.transport_mode
    if version and (version, mode) != (conn.detected_version, conn.detected_mode):
        db.execute(
            update(OdooConnection).where(OdooConnection.id == conn.id)
            .values(detected_version=version, detected_mode=mode)
        )
