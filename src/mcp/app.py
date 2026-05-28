"""FastAPI MCP service — port 8000."""

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import bcrypt
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.controller.crypto import decrypt_credential
from src.shared.database import SessionLocal, init_db
from src.shared.models import ApiKey, OdooConnection, RequestLog
from src.mcp import tools as tool_module
from src.mcp.odoo_client import OdooClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("MCP service started")
    yield
    logger.info("MCP service stopped")


app = FastAPI(title="Odoo MCP Service", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _get_db() -> Session:
    return SessionLocal()


def _validate_api_key(raw_key: str, db: Session) -> ApiKey | None:
    rows = db.execute(select(ApiKey).where(ApiKey.is_active == True)).scalars().all()  # noqa: E712
    for row in rows:
        if bcrypt.checkpw(raw_key.encode(), row.key_hash.encode()):
            return row
    return None


def _get_active_connection(db: Session) -> OdooConnection:
    conn = db.execute(
        select(OdooConnection).where(OdooConnection.is_active == True)  # noqa: E712
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=503, detail="No active Odoo connection configured")
    return conn


def _build_client(conn: OdooConnection) -> OdooClient:
    credential = decrypt_credential(conn.credential)
    return OdooClient(url=conn.url, database=conn.database, username=conn.username, password=credential)


def _log_request(
    db: Session,
    tool_name: str,
    status: str,
    duration_ms: int,
    connection_id: int | None = None,
    api_key_id: int | None = None,
    error_message: str | None = None,
) -> None:
    db.add(RequestLog(
        tool_name=tool_name, status=status, duration_ms=duration_ms,
        connection_id=connection_id, api_key_id=api_key_id, error_message=error_message,
    ))
    db.commit()


@app.get("/health")
async def health():
    db = _get_db()
    try:
        conn = db.execute(
            select(OdooConnection).where(OdooConnection.is_active == True)  # noqa: E712
        ).scalar_one_or_none()
        return {"status": "ok", "active_connection": conn.name if conn else None}
    finally:
        db.close()


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    raw_key = request.headers.get("X-API-Key", "")
    db = _get_db()
    try:
        api_key_row = _validate_api_key(raw_key, db) if raw_key else None
        if api_key_row is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        body = await request.json()
        method = body.get("method", "")
        req_id = body.get("id")
        params = body.get("params", {})

        # ---- tools/list ----
        if method == "tools/list":
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in tool_module.TOOLS
                ]},
            })

        # ---- tools/call ----
        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments: dict[str, Any] = params.get("arguments", {})

            conn = _get_active_connection(db)
            client = _build_client(conn)

            start = time.time()
            status = "success"
            error_msg: str | None = None
            content: list[dict] = []
            try:
                tool_results = await tool_module.call_tool(tool_name, arguments, client)
                content = [{"type": c.type, "text": c.text} for c in tool_results]
            except KeyError as exc:
                status = "error"
                error_msg = f"Missing required argument: {exc}"
                content = [{"type": "text", "text": error_msg}]
            except Exception as exc:
                status = "error"
                error_msg = str(exc)
                content = [{"type": "text", "text": f"Error: {exc}"}]

            duration_ms = int((time.time() - start) * 1000)
            _log_request(db, tool_name, status, duration_ms, conn.id, api_key_row.id, error_msg)
            db.execute(
                update(ApiKey).where(ApiKey.id == api_key_row.id).values(
                    request_count=ApiKey.request_count + 1,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

            if status == "error":
                return JSONResponse({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": error_msg},
                })
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": content},
            })

        # ---- initialize / ping ----
        if method in ("initialize", "ping"):
            return JSONResponse({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "odoo-mcp-server", "version": "2.0.0"},
                },
            })

        return JSONResponse({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })

    finally:
        db.close()
