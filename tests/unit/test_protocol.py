"""JSON-RPC/MCP handling, plus the HTTP layer: auth, 202/405, Origin check, logging."""

import asyncio
import json

import bcrypt
import pytest
from fastapi.testclient import TestClient

from src.mcp import protocol
from src.mcp.transport.base import OdooError
from tests.conftest import FakeTransport, default_handlers, make_client


def run(payload, scope="write", version=None, client=None):
    records = []
    rc = protocol.RequestContext(
        get_client=lambda: client, scope=scope, protocol_version=version, on_tool_call=records.append,
    )
    status, body = asyncio.run(protocol.handle_payload(payload, rc))
    return status, body, records


def req(method, params=None, id_=1):
    msg = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


@pytest.mark.parametrize("requested, answered", [
    ("2025-11-25", "2025-11-25"),
    ("2025-06-18", "2025-06-18"),
    ("2024-11-05", "2024-11-05"),
    ("1999-01-01", "2025-11-25"),
])
def test_initialize_negotiates_version(requested, answered):
    status, body, _ = run(req("initialize", {"protocolVersion": requested, "capabilities": {},
                                             "clientInfo": {"name": "t", "version": "1"}}))
    result = body["result"]
    assert status == 200 and result["protocolVersion"] == answered
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"] == {"name": "odoo-mcp-server", "title": "Odoo MCP Server", "version": "3.0.0"}
    assert "get_context" in result["instructions"]


def test_notifications_and_responses_get_202_without_body():
    assert run({"jsonrpc": "2.0", "method": "notifications/initialized"})[:2] == (202, None)
    assert run({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})[:2] == (202, None)
    assert run({"jsonrpc": "2.0", "id": 5, "result": {}})[:2] == (202, None)


def test_ping_unknown_method_and_invalid_request():
    assert run(req("ping"))[1] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert run(req("resources/list"))[1]["error"]["code"] == -32601
    assert run({"id": 1, "method": "ping"})[1]["error"]["code"] == -32600  # missing jsonrpc
    assert run([])[1]["error"]["code"] == -32600
    assert run("nope")[1]["error"]["code"] == -32600


def test_batch_returns_responses_but_not_for_notifications():
    status, body, _ = run([req("ping", id_=1), {"jsonrpc": "2.0", "method": "notifications/initialized"},
                           req("ping", id_=2)])
    assert status == 200 and [r["id"] for r in body] == [1, 2]
    assert run([{"jsonrpc": "2.0", "method": "notifications/initialized"}])[:2] == (202, None)


def test_tools_list_annotations_and_read_scope():
    _, body, _ = run(req("tools/list"), version="2025-06-18")
    tools = body["result"]["tools"]
    assert len(tools) == 13
    by_name = {t["name"]: t for t in tools}
    assert by_name["delete_record"]["annotations"]["destructiveHint"] is True
    assert "outputSchema" in by_name["search_records"] and "outputSchema" not in by_name["get_record"]
    _, body, _ = run(req("tools/list"))  # no header → 2025-03-26: no outputSchema
    assert all("outputSchema" not in t for t in body["result"]["tools"])
    _, body, _ = run(req("tools/list"), scope="read")
    names = {t["name"] for t in body["result"]["tools"]}
    assert len(names) == 9 and not names & {"create_record", "update_record", "delete_record", "execute_method"}


def _client():
    t = FakeTransport(handlers=default_handlers())
    t.handlers[("res.partner", "search_count")] = lambda ids, kw, ctx: 42
    t.handlers[("res.partner", "search_read")] = lambda ids, kw, ctx: [{"id": 1, "display_name": "الشركة"}]
    return make_client(t)


def test_tools_call_success_structured_content_by_version():
    client = _client()
    status, body, records = run(req("tools/call", {"name": "search_count", "arguments": {"model": "res.partner"}}),
                                version="2025-06-18", client=client)
    result = body["result"]
    assert result["isError"] is False and result["content"][0]["text"] == '{"count":42}'
    assert result["structuredContent"] == {"count": 42}
    assert records[0].status == "success" and records[0].response_bytes == 12 and records[0].transport == "json2"
    _, body, _ = run(req("tools/call", {"name": "search_count", "arguments": {"model": "res.partner"}}),
                     version="2025-03-26", client=client)
    assert "structuredContent" not in body["result"]


def test_tool_errors_are_results_with_hints():
    client = _client()
    _, body, records = run(req("tools/call", {"name": "search_records",
                                              "arguments": {"model": "res.partner", "fields": ["nam"]}}), client=client)
    result = body["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("InvalidArguments: Unknown field 'nam' on res.partner. Did you mean: name")
    assert "Hint: call get_model_fields" in result["content"][0]["text"]
    assert records[0].status == "error"

    def boom(ids, kw, ctx):
        raise OdooError("odoo.exceptions.AccessError", "You are not allowed to access 'Contact'", 403)
    client.transport.handlers[("res.partner", "search_count")] = boom
    _, body, _ = run(req("tools/call", {"name": "search_count", "arguments": {"model": "res.partner"}}), client=client)
    assert body["result"]["content"][0]["text"] == (
        "AccessError: You are not allowed to access 'Contact'\nHint: the connection's Odoo user lacks rights for this")


def test_unknown_tool_and_read_only_key_are_protocol_errors():
    _, body, _ = run(req("tools/call", {"name": "nope", "arguments": {}}))
    assert body["error"]["code"] == -32602
    _, body, _ = run(req("tools/call", {"name": "create_record", "arguments": {"model": "res.partner"}}), scope="read")
    assert body["error"]["code"] == -32602 and "read-only" in body["error"]["message"]


def test_read_key_blocklist(monkeypatch):
    _, body, _ = run(req("tools/call", {"name": "search_records", "arguments": {"model": "ir.config_parameter"}}),
                     scope="read", client=_client())
    assert body["result"]["isError"] and "not available to read-only" in body["result"]["content"][0]["text"]


def test_no_active_connection_is_a_tool_error():
    def no_conn():
        raise OdooError("NoActiveConnection", "No active Odoo connection is configured")
    rc = protocol.RequestContext(get_client=no_conn)
    _, body = asyncio.run(protocol.handle_payload(
        req("tools/call", {"name": "search_count", "arguments": {"model": "res.partner"}}), rc))
    assert body["result"]["isError"] and "activate an Odoo connection" in body["result"]["content"][0]["text"]


def test_redact_hides_secrets():
    assert protocol.redact({"values": {"password": "x", "name": "n", "api_key": "k"}, "token": "t"}) == {
        "values": {"password": "***", "name": "n", "api_key": "***"}, "token": "***"}


# ── HTTP layer ───────────────────────────────────────────────────────────────

RAW_KEY = "abcdEFGH-test-key-0123456789"


@pytest.fixture
def http(monkeypatch):
    from src.mcp import app as mcp_app
    from src.shared.database import SessionLocal, init_db
    from src.shared.models import ApiKey, OdooConnection, RequestLog

    init_db()
    db = SessionLocal()
    db.query(RequestLog).delete()
    db.query(ApiKey).delete()
    db.query(OdooConnection).delete()
    db.add(ApiKey(name="t", key_hash=bcrypt.hashpw(RAW_KEY.encode(), bcrypt.gensalt(4)).decode(),
                  key_prefix=RAW_KEY[:8], scope="write"))
    db.add(OdooConnection(name="c", url="http://odoo.test", database="db", username="admin",
                          credential="x", credential_type="api_key", is_active=True))
    db.commit()
    db.close()
    mcp_app._key_cache.clear()
    client = _client()
    monkeypatch.setattr(mcp_app, "get_client", lambda conn: client)
    with TestClient(mcp_app.app) as tc:
        yield tc


def test_http_auth_headers(http):
    ping = req("ping")
    assert http.post("/mcp", json=ping).status_code == 401
    assert http.post("/mcp", json=ping, headers={"X-API-Key": "wrong-key-123"}).status_code == 401
    assert http.post("/mcp", json=ping, headers={"X-API-Key": RAW_KEY}).json()["result"] == {}
    assert http.post("/mcp", json=ping, headers={"Authorization": f"Bearer {RAW_KEY}"}).json()["result"] == {}


def test_http_notification_202_empty_body(http):
    r = http.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                  headers={"X-API-Key": RAW_KEY})
    assert r.status_code == 202 and r.content == b""


def test_http_get_is_405_and_parse_error(http):
    assert http.get("/mcp").status_code == 405
    r = http.post("/mcp", content=b"{not json", headers={"X-API-Key": RAW_KEY, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700


def test_http_origin_check(http):
    r = http.post("/mcp", json=req("ping"), headers={"X-API-Key": RAW_KEY, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_http_tool_call_logs_size_transport_and_arabic(http):
    from src.shared.database import SessionLocal
    from src.shared.models import ApiKey, RequestLog

    r = http.post("/mcp", json=req("tools/call", {"name": "search_records", "arguments": {"model": "res.partner"}}),
                  headers={"X-API-Key": RAW_KEY, "MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 200
    assert "الشركة".encode() in r.content and b"\\u" not in r.content
    body = r.json()["result"]
    assert body["structuredContent"]["records"][0]["display_name"] == "الشركة"
    db = SessionLocal()
    log = db.query(RequestLog).one()
    assert log.tool_name == "search_records" and log.transport == "json2" and log.response_bytes > 0
    assert db.query(ApiKey).one().request_count == 1
    db.close()
