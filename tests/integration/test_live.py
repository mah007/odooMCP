"""Live checks against a real Odoo. Skipped unless the environment names one.

    ODOO_URL, ODOO_DB, ODOO_LOGIN          required
    ODOO_API_KEY                           API key with RPC scope → runs the json2 and xmlrpc suites
    ODOO_PASSWORD                          optional → also runs xmlrpc with a password
    ODOO_ALLOW_WRITES=1                    enables the self-cleaning write test (sandbox only)
    ODOO_DOCKER_CONTAINER                  enables the "no deprecation warnings" check for JSON-2
    ODOO_EXPECT_ARCDESOL=1                 enables the Arc De Sol specific company checks

Run:  pytest tests/integration -v
"""

import asyncio
import os
import subprocess
import time
from datetime import datetime, timezone

import pytest

from src.mcp import protocol, shaping
from src.mcp.odoo_client import ConnectionConfig, OdooClient

URL = os.environ.get("ODOO_URL")
DB = os.environ.get("ODOO_DB")
LOGIN = os.environ.get("ODOO_LOGIN")
API_KEY = os.environ.get("ODOO_API_KEY")
PASSWORD = os.environ.get("ODOO_PASSWORD")

pytestmark = pytest.mark.skipif(not (URL and DB and LOGIN and (API_KEY or PASSWORD)),
                                reason="ODOO_URL / ODOO_DB / ODOO_LOGIN and a credential are not set")

MODES = []
if API_KEY:
    MODES += [("json2", "api_key"), ("xmlrpc", "api_key")]
if PASSWORD:
    MODES += [("xmlrpc", "password")]


def make(mode: str, cred: str) -> OdooClient:
    return OdooClient(ConnectionConfig(
        url=URL, database=DB, username=LOGIN, secret=API_KEY if cred == "api_key" else PASSWORD,
        credential_type=cred, api_mode=mode, verify_ssl=False,
    ))


@pytest.fixture(scope="module", params=MODES, ids=[f"{m}-{c}" for m, c in MODES])
def client(request):
    c = make(*request.param)
    yield c
    c.close()


def call(client: OdooClient, tool: str, version: str = "2025-06-18", **args) -> tuple[dict, str]:
    rc = protocol.RequestContext(get_client=lambda: client, protocol_version=version)
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    _, body = asyncio.run(protocol.handle_payload(msg, rc))
    result = body["result"]
    return result, result["content"][0]["text"]


def ok(client, tool, **args) -> tuple[dict, str]:
    result, text = call(client, tool, **args)
    assert result["isError"] is False, text
    return result, text


def nbytes(text: str) -> int:
    return len(text.encode())


# ── Every read tool works ────────────────────────────────────────────────────

READ_CALLS = [
    ("get_context", {}),
    ("list_models", {"search": "partner"}),
    ("get_model_fields", {"model": "res.partner", "filter": "required"}),
    ("model_info", {"model": "res.partner"}),
    ("search_records", {"model": "res.partner", "fields": ["name", "email"], "limit": 5}),
    ("search_count", {"model": "res.partner"}),
    ("get_record", {"model": "res.partner", "ids": [1]}),
    ("name_search", {"model": "res.company", "name": "a"}),
    ("aggregate", {"model": "res.partner", "groupby": ["company_id"]}),
    ("execute_method", {"model": "res.users", "method": "context_get"}),
]


@pytest.mark.parametrize("tool, args", READ_CALLS, ids=[c[0] for c in READ_CALLS])
def test_read_tool(client, tool, args):
    _, text = ok(client, tool, **args)
    assert nbytes(text) <= shaping.MAX_RESPONSE_BYTES


def test_transport_in_use(client):
    result, _ = ok(client, "get_context")
    assert result["structuredContent"]["odoo"]["transport"] == client.config.api_mode


# ── Size targets (acceptance 1-5, 7) ─────────────────────────────────────────

def test_size_search_partner_default(client):
    _, text = ok(client, "search_records", model="res.partner")
    assert nbytes(text) < 10_000


def test_size_search_accounts_no_limit(client):
    result, text = ok(client, "search_records", model="account.account")
    assert nbytes(text) < 15_000
    data = result["structuredContent"]
    if data["total"] > data["limit"]:
        assert data["next_offset"] == data["limit"]


def test_size_fields_partner(client):
    assert nbytes(ok(client, "get_model_fields", model="res.partner")[1]) <= 40_000


def test_size_fields_sale_order(client):
    result, text = call(client, "get_model_fields", model="sale.order")
    if result["isError"]:
        pytest.skip(f"sale.order not available: {text[:100]}")
    assert nbytes(text) <= 15_000


def test_size_list_models(client):
    assert nbytes(ok(client, "list_models")[1]) <= 30_000


def test_size_get_record_partner_compact(client):
    assert nbytes(ok(client, "get_record", model="res.partner", ids=[1])[1]) <= shaping.MAX_RESPONSE_BYTES


# ── Content checks ───────────────────────────────────────────────────────────

def test_arabic_unescaped(client):
    _, text = ok(client, "search_records", model="res.lang", domain=[["code", "=", "ar_001"]],
                 fields=["name", "code"], context={"active_test": False})
    if '"total":0' in text:
        pytest.skip("Arabic is not available in this database")
    assert "الْعَرَبيّة" in text or "العربية" in text
    assert "\\u" not in text


def test_aggregate_journals_by_company(client):
    result, _ = ok(client, "aggregate", model="account.journal", groupby=["company_id"])
    groups = result["structuredContent"]["groups"]
    assert groups and all(isinstance(g["keys"]["company_id"], list) for g in groups)
    assert all(isinstance(g["count"], int) for g in groups)


def test_tool_error_is_a_result(client):
    result, text = call(client, "search_records", model="res.partner", fields=["no_such_field_x"])
    assert result["isError"] is True and "Hint:" in text


def test_v2_style_calls(client):
    _, text = ok(client, "search_records", model="res.partner", domain=[["id", "=", 1]], fields=["name"], limit=1)
    assert '"id":1' in text
    _, text = ok(client, "execute_method", model="res.partner", method="read", args=[[1], ["name"]])
    assert '"id":1' in text


def test_model_info_methods(client):
    result, _ = ok(client, "model_info", model="res.partner")
    methods = result["structuredContent"]["methods"]
    if client.mode == "json2":
        assert isinstance(methods, dict) and methods, methods
    else:
        assert isinstance(methods, (dict, str))


@pytest.mark.skipif(not os.environ.get("ODOO_EXPECT_ARCDESOL"), reason="Arc De Sol specific")
def test_arcdesol_companies_and_branches(client):
    result, _ = ok(client, "get_context")
    companies = {c["id"]: c for c in result["structuredContent"]["companies"]}
    assert len(companies) == 6
    assert companies[110]["is_branch"] and companies[111]["is_branch"]
    assert companies[110]["parent_id"][0] == 108 and companies[111]["parent_id"][0] == 109


# ── Writes (sandbox only) ────────────────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("ODOO_ALLOW_WRITES"), reason="ODOO_ALLOW_WRITES is not set")
def test_write_cycle_cleans_up(client):
    name = f"MCP v3 test {client.mode} {int(time.time() * 1000)}"
    ids: list[int] = []
    try:
        result, _ = ok(client, "create_record", model="res.partner", values={"name": name})
        ids = result["structuredContent"]["ids"]
        assert len(ids) == 1
        ok(client, "update_record", model="res.partner", ids=ids, values={"ref": "MCP-V3"})
        result, _ = ok(client, "get_record", model="res.partner", ids=ids, fields=["ref"])
        assert result["structuredContent"]["records"][0]["ref"] == "MCP-V3"
        ok(client, "delete_record", model="res.partner", ids=ids)
        ids = []
        result, _ = ok(client, "search_count", model="res.partner", domain=[["name", "=", name]],
                       context={"active_test": False})
        assert result["structuredContent"]["count"] == 0
    finally:
        if ids:
            client.unlink("res.partner", ids)


# ── JSON-2 leaves no deprecation warnings (acceptance 11) ────────────────────

@pytest.mark.skipif(not (API_KEY and os.environ.get("ODOO_DOCKER_CONTAINER")),
                    reason="needs ODOO_API_KEY and ODOO_DOCKER_CONTAINER")
def test_json2_run_logs_no_deprecation_warnings():
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    time.sleep(1)
    c = make("auto", "api_key")
    try:
        for tool, args in READ_CALLS:
            ok(c, tool, **args)
        assert c.mode == "json2"
    finally:
        c.close()
    time.sleep(1)
    logs = subprocess.run(
        ["docker", "logs", "--since", since, os.environ["ODOO_DOCKER_CONTAINER"]],
        capture_output=True, text=True, check=True,
    )
    output = logs.stdout + logs.stderr
    assert "endpoints are deprecated" not in output
