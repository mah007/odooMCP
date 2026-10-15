"""Version detection, mode selection, JSON-2 and XML-RPC request building."""

import json
import xmlrpc.client

import httpx
import pytest
import respx

from src.mcp.transport.base import MethodNotFound, OdooError
from src.mcp.transport.detect import VersionInfo, detect_version, parse_version_info, select_mode
from src.mcp.transport.json2 import Json2Transport
from src.mcp.transport.xmlrpc import XmlRpcTransport, fault_to_error

URL = "http://odoo.test"


# ── Version parsing and mode selection ───────────────────────────────────────

@pytest.mark.parametrize("info, raw, major, minor, saas", [
    ([20, 0, 0, "final", 0, "e"], "20.0+e-20260926", 20, 0, False),
    (["saas~18", 4, 0, "final", 0, ""], None, 18, 4, True),
    ((17, 0, 0, "final", 0, ""), None, 17, 0, False),
    ([10, 0, 0, "final", 0], "10.0", 10, 0, False),
])
def test_parse_version_info(info, raw, major, minor, saas):
    v = parse_version_info(info, raw)
    assert (v.major, v.minor, v.saas) == (major, minor, saas)
    assert v.raw == (raw or (f"saas~{major}.{minor}" if saas else f"{major}.{minor}"))


def test_parse_version_info_rejects_garbage():
    with pytest.raises(ValueError):
        parse_version_info([])
    with pytest.raises(ValueError):
        parse_version_info(["master"])


V = lambda major, saas=False: VersionInfo(major, 0, f"{major}.0", saas)  # noqa: E731


@pytest.mark.parametrize("api_mode, version, cred, expected", [
    ("auto", V(20), "api_key", "json2"),
    ("auto", V(19), "api_key", "json2"),
    ("auto", V(18), "api_key", "xmlrpc"),
    ("auto", V(18, saas=True), "api_key", "xmlrpc"),
    ("auto", V(12), "password", "xmlrpc"),
    ("auto", V(20), "password", "xmlrpc"),  # JSON-2 cannot use a password
    ("xmlrpc", V(20), "api_key", "xmlrpc"),
    ("json2", V(20), "api_key", "json2"),
])
def test_select_mode(api_mode, version, cred, expected):
    mode, note = select_mode(api_mode, version, cred)
    assert mode == expected
    if api_mode == "auto" and version.major >= 19 and cred == "password":
        assert "API key with RPC scope" in note
    else:
        assert note is None


def test_select_mode_json2_on_old_odoo_fails_clearly():
    with pytest.raises(OdooError, match="JSON-2 needs Odoo 19"):
        select_mode("json2", V(17), "api_key")


@respx.mock
def test_detect_version_uses_web_version_first():
    respx.get(f"{URL}/web/version").respond(json={"version_info": [20, 0, 0, "final", 0, ""], "version": "20.0"})
    assert detect_version(URL).major == 20


@respx.mock
def test_detect_version_falls_back_to_webclient_version_info():
    respx.get(f"{URL}/web/version").respond(404)
    respx.post(f"{URL}/web/webclient/version_info").respond(
        json={"jsonrpc": "2.0", "id": 1, "result": {"server_version_info": [16, 0, 0, "final", 0, ""],
                                                    "server_version": "16.0"}}
    )
    v = detect_version(URL)
    assert (v.major, v.raw) == (16, "16.0")


# ── JSON-2 ───────────────────────────────────────────────────────────────────

@respx.mock
def test_json2_request_building():
    route = respx.post(f"{URL}/json/2/res.partner/write").respond(json=True)
    t = Json2Transport(URL, "mydb", "admin", "secret-key")
    assert t.call("res.partner", "write", ids=[1, 2], kwargs={"vals": {"name": "x"}}, context={"lang": "ar_001"}) is True
    req = route.calls.last.request
    assert req.headers["Authorization"] == "bearer secret-key"
    assert req.headers["X-Odoo-Database"] == "mydb"
    assert req.headers["User-Agent"].startswith("odoo-mcp-server/3")
    assert json.loads(req.content) == {"vals": {"name": "x"}, "ids": [1, 2], "context": {"lang": "ar_001"}}


@respx.mock
def test_json2_model_method_has_no_ids_key():
    route = respx.post(f"{URL}/json/2/res.partner/search_count").respond(json=7)
    t = Json2Transport(URL, "db", "admin", "k")
    assert t.call("res.partner", "search_count", kwargs={"domain": []}) == 7
    assert json.loads(route.calls.last.request.content) == {"domain": []}


def _odoo_error(name, message):
    return {"name": name, "message": message, "arguments": [message], "context": {},
            "debug": "Traceback (most recent call last):\n  secret internals"}


@respx.mock
@pytest.mark.parametrize("status, name, cls", [
    (401, "werkzeug.exceptions.Unauthorized", OdooError),
    (403, "odoo.exceptions.AccessError", OdooError),
    (404, "werkzeug.exceptions.NotFound", MethodNotFound),
    (422, "werkzeug.exceptions.UnprocessableEntity", OdooError),
    (500, "odoo.exceptions.ValidationError", OdooError),
])
def test_json2_error_mapping(status, name, cls):
    respx.post(f"{URL}/json/2/res.partner/write").respond(status, json=_odoo_error(name, "boom"))
    t = Json2Transport(URL, "db", "admin", "k")
    with pytest.raises(cls) as info:
        t.call("res.partner", "write", ids=[1], kwargs={"vals": {}})
    err = info.value
    assert err.status == status and err.name == name
    assert "Traceback" not in str(err) and "secret internals" not in err.message
    if status == 401:
        assert "RPC scope" in err.message


@respx.mock
def test_json2_uid_lookup_is_cached():
    route = respx.post(f"{URL}/json/2/res.users/search_read").respond(json=[{"id": 9}])
    t = Json2Transport(URL, "db", "bob", "k")
    assert t.uid() == 9 and t.uid() == 9
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content)["domain"] == [["login", "=", "bob"]]


@respx.mock
def test_json2_connection_error():
    respx.post(f"{URL}/json/2/res.partner/read").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(OdooError, match="Cannot reach"):
        Json2Transport(URL, "db", "admin", "k").call("res.partner", "read", ids=[1])


# ── XML-RPC ──────────────────────────────────────────────────────────────────

class FakeProxy:
    def __init__(self, log, endpoint):
        self.log, self.endpoint = log, endpoint

    def authenticate(self, db, login, secret, ctx):
        self.log.append(("authenticate", db, login))
        return 2

    def execute_kw(self, db, uid, secret, model, method, args, kwargs):
        self.log.append(("execute_kw", model, method, args, kwargs))
        if method == "create":
            return 41
        return True


def _xml(major=17):
    log: list = []
    t = XmlRpcTransport(URL, "db", "admin", "pw", major=major, proxy_factory=lambda ep: FakeProxy(log, ep))
    return t, log


def test_xmlrpc_execute_kw_args():
    t, log = _xml()
    t.call("res.partner", "write", ids=[1, 2], kwargs={"vals": {"name": "x"}}, context={"lang": "fr_FR"})
    t.call("res.partner", "search_count", kwargs={"domain": []})
    assert log[0] == ("authenticate", "db", "admin")
    assert log[1] == ("execute_kw", "res.partner", "write", [[1, 2]], {"vals": {"name": "x"}, "context": {"lang": "fr_FR"}})
    assert log[2] == ("execute_kw", "res.partner", "search_count", [[]], {})  # positional on XML-RPC
    assert sum(1 for entry in log if entry[0] == "authenticate") == 1  # uid cached


def test_xmlrpc_create_on_odoo_11_is_one_call_per_record():
    t, log = _xml(major=11)
    assert t.call("res.partner", "create", kwargs={"vals_list": [{"name": "a"}, {"name": "b"}]}) == [41, 41]
    creates = [entry for entry in log if entry[0] == "execute_kw"]
    assert [c[3] for c in creates] == [[{"name": "a"}], [{"name": "b"}]]
    assert all("vals_list" not in c[4] for c in creates)


def test_xmlrpc_create_passes_vals_list_positionally():
    # odoo/service/model.py call_kw reads args[0] for create; a keyword vals_list raises IndexError
    t, log = _xml(major=17)
    t.call("res.partner", "create", kwargs={"vals_list": [{"name": "a"}]}, context={"lang": "en_US"})
    assert log[-1] == ("execute_kw", "res.partner", "create", [[{"name": "a"}]], {"context": {"lang": "en_US"}})


def test_xmlrpc_renamed_parameters_are_sent_positionally():
    t, log = _xml(major=15)
    t.call("res.partner", "search_count", kwargs={"domain": [["a", "=", 1]]})
    t.call("res.partner", "name_search", kwargs={"name": "ab", "domain": [], "operator": "ilike", "limit": 5})
    t.call("res.partner", "default_get", kwargs={"fields_list": ["name"]})
    assert log[-3][3:] == ([[["a", "=", 1]]], {})
    assert log[-2][3:] == (["ab", [], "ilike", 5], {})
    assert log[-1][3:] == ([["name"]], {})


def test_xmlrpc_failed_authentication():
    t = XmlRpcTransport(URL, "db", "admin", "pw", proxy_factory=lambda ep: type(
        "P", (), {"authenticate": lambda self, *a: False})())
    with pytest.raises(OdooError, match="rejected the login") as info:
        t.uid()
    assert info.value.status == 401


def test_fault_mapping():
    tb = ("Traceback (most recent call last):\n  File \"x.py\", line 1, in f\n"
          "ValueError: Invalid field 'foo' on model 'res.partner'\n")
    err = fault_to_error(xmlrpc.client.Fault(1, tb))
    assert err.name == "ValueError" and "Invalid field 'foo'" in err.message
    err = fault_to_error(xmlrpc.client.Fault(4, "You are not allowed to modify 'Contact'"))
    assert err.name == "odoo.exceptions.AccessError"
    err = fault_to_error(xmlrpc.client.Fault(2, "Record does not exist or has been deleted."))
    assert err.short_name == "MissingError"
    tb = "Traceback\nAttributeError: The method 'res.partner.nope' does not exist\n"
    assert isinstance(fault_to_error(xmlrpc.client.Fault(1, tb)), MethodNotFound)
