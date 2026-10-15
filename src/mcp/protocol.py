"""JSON-RPC 2.0 + MCP message handling (stateless Streamable HTTP, JSON responses only)."""

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from src.mcp import shaping, tools
from src.mcp.odoo_client import OdooClient
from src.mcp.transport.base import OdooError

SERVER_VERSION = "3.0.0"
SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
# Spec: without an MCP-Protocol-Version header the server assumes 2025-03-26.
DEFAULT_VERSION = "2025-03-26"
STRUCTURED_SINCE = "2025-06-18"
SERVER_INFO = {"name": "odoo-mcp-server", "title": "Odoo MCP Server", "version": SERVER_VERSION}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700, -32600, -32601, -32602, -32603,
)

DEFAULT_READ_BLOCKLIST = "ir.config_parameter,res.users.apikeys,res.groups,base.automation"
_SECRET_KEY_RE = re.compile(r"password|token|secret|key", re.I)


def read_key_blocklist() -> set[str]:
    raw = os.environ.get("MCP_READ_KEY_BLOCKLIST", DEFAULT_READ_BLOCKLIST)
    return {m.strip() for m in raw.split(",") if m.strip()}


@dataclass
class ToolCallRecord:
    tool: str
    status: str
    duration_ms: int
    response_bytes: int
    transport: str | None
    error: str | None


@dataclass
class RequestContext:
    get_client: Callable[[], OdooClient]
    scope: str = "write"
    protocol_version: str | None = None
    on_tool_call: Callable[[ToolCallRecord], None] | None = None

    @property
    def version(self) -> str:
        return self.protocol_version if self.protocol_version in SUPPORTED_VERSIONS else DEFAULT_VERSION

    @property
    def structured(self) -> bool:
        return self.version >= STRUCTURED_SINCE


def redact(value: Any) -> Any:
    """Hide values whose key looks like a credential before logging arguments."""
    if isinstance(value, dict):
        return {k: "***" if _SECRET_KEY_RE.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _ok(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def parse_error() -> dict:
    return _error(None, PARSE_ERROR, "Parse error: the body is not valid JSON")


def negotiate(requested: Any) -> str:
    return requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]


def hint_for(exc: OdooError) -> str | None:
    msg = exc.message
    name = exc.short_name
    if "Invalid field" in msg or "Unknown field" in msg or "invalid field" in msg.lower():
        return "call get_model_fields"
    if exc.status == 401 or name in ("AuthenticationError", "AccessDenied") or "Invalid apikey" in msg:
        return "the Odoo API key is invalid or expired; fix the connection in the admin UI"
    if name == "AccessError" or exc.status == 403:
        return "the connection's Odoo user lacks rights for this"
    if name == "MissingError" or "does not exist or has been deleted" in msg:
        return 'the ids may be archived or deleted; try context {"active_test": false}'
    if exc.status == 404 or name in ("NotFound", "AttributeError"):
        return "check the model and method names (list_models, model_info)"
    if exc.status == 422:
        return "check the argument names against model_info's method signatures; @api.model methods take no ids"
    if name == "Timeout":
        return "narrow the domain, ask for fewer fields or lower the limit"
    if name == "NoActiveConnection":
        return "activate an Odoo connection in the admin UI"
    return None


def error_result(name: str, message: str, hint: str | None = None) -> dict:
    text = f"{name}: {message}"
    if hint:
        text += f"\nHint: {hint}"
    return {"content": [{"type": "text", "text": text}], "isError": True}


def list_tools(rc: RequestContext) -> list[dict]:
    out = []
    for tool in tools.TOOLS:
        if rc.scope == "read" and tool["name"] in tools.WRITE_TOOLS:
            continue
        entry = {k: v for k, v in tool.items() if k != "outputSchema"}
        if rc.structured and "outputSchema" in tool:
            entry["outputSchema"] = tool["outputSchema"]
        out.append(entry)
    return out


async def call_tool(req_id: Any, params: dict, rc: RequestContext) -> dict:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    tool = tools.TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None:
        return _error(req_id, INVALID_PARAMS, f"Unknown tool: {name}")
    if rc.scope == "read" and name in tools.WRITE_TOOLS:
        return _error(req_id, INVALID_PARAMS, f"{name}: this API key is read-only")
    if not isinstance(arguments, dict):
        return _error(req_id, INVALID_PARAMS, "`arguments` must be an object")

    logger.debug("tools/call {} {}", name, redact(arguments))
    start = time.monotonic()
    client: OdooClient | None = None
    error_text: str | None = None
    try:
        args = tools.validate_arguments(tool, arguments)
        if rc.scope == "read" and args.get("model") in read_key_blocklist():
            raise tools.ToolInputError(f"The model {args['model']} is not available to read-only API keys")
        client = rc.get_client()
        data = await asyncio.to_thread(tools.HANDLERS[name], client, args)
        text = data if isinstance(data, str) else shaping.dumps(data)
        result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
        if rc.structured and isinstance(data, dict):
            result["structuredContent"] = data
    except tools.ToolInputError as exc:
        result = error_result("InvalidArguments", exc.message, exc.hint)
    except OdooError as exc:
        result = error_result(exc.short_name, exc.message, hint_for(exc))
    except Exception as exc:  # noqa: BLE001 — every failure must reach the model as a result
        logger.exception("Tool {} failed", name)
        result = error_result(type(exc).__name__, str(exc))
    if result["isError"]:
        error_text = result["content"][0]["text"]
    if rc.on_tool_call:
        rc.on_tool_call(ToolCallRecord(
            tool=name,
            status="error" if result["isError"] else "success",
            duration_ms=int((time.monotonic() - start) * 1000),
            response_bytes=len(result["content"][0]["text"].encode()),
            transport=client.transport_mode if client else None,
            error=error_text,
        ))
    return _ok(req_id, result)


async def handle_message(msg: Any, rc: RequestContext) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications and client responses."""
    if not isinstance(msg, dict):
        return _error(None, INVALID_REQUEST, "Invalid Request: expected a JSON object")
    if "method" not in msg:
        if "result" in msg or "error" in msg:
            return None  # a response to a server request; we never send any, so ignore it
        return _error(msg.get("id"), INVALID_REQUEST, "Invalid Request: missing method")
    if "id" not in msg:
        return None  # notification (notifications/initialized, notifications/cancelled, …)
    req_id = msg["id"]
    method = msg["method"]
    if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error(req_id, INVALID_REQUEST, "Invalid Request: jsonrpc must be '2.0' and method a string")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": negotiate(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": tools.INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": list_tools(rc)})
    if method == "tools/call":
        return await call_tool(req_id, params, rc)
    return _error(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")


async def handle_payload(payload: Any, rc: RequestContext) -> tuple[int, Any]:
    """Returns (HTTP status, JSON body or None). 202 with no body when nothing needs an answer."""
    if isinstance(payload, list):
        if not payload:
            return 400, _error(None, INVALID_REQUEST, "Invalid Request: empty batch")
        responses = [r for r in [await handle_message(m, rc) for m in payload] if r is not None]
        return (200, responses) if responses else (202, None)
    response = await handle_message(payload, rc)
    if response is None:
        return 202, None
    return 200, response
