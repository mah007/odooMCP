"""Tool handlers against a fake transport: defaults, pagination, context, grouping, args mapping."""

import pytest

from src.mcp import tools
from src.mcp.transport.base import OdooError
from tests.conftest import V17, V20, FakeTransport, default_handlers, make_client


def call(client, name, **args):
    tool = tools.TOOLS_BY_NAME[name]
    return tools.HANDLERS[name](client, tools.validate_arguments(tool, args))


# ── Argument validation and domains ──────────────────────────────────────────

def test_validate_arguments_coerces_llm_style_values():
    tool = tools.TOOLS_BY_NAME["get_record"]
    args = tools.validate_arguments(tool, {"model": "res.partner", "ids": ["1", 2], "include_binary": "false"})
    assert args["ids"] == [1, 2] and args["include_binary"] is False
    args = tools.validate_arguments(tool, {"model": "res.partner", "ids": 5})
    assert args["ids"] == [5]
    with pytest.raises(tools.ToolInputError, match="Missing required"):
        tools.validate_arguments(tool, {"model": "res.partner"})
    with pytest.raises(tools.ToolInputError, match="at most 100"):
        tools.validate_arguments(tool, {"model": "res.partner", "ids": list(range(101))})


@pytest.mark.parametrize("domain, expected", [
    (None, []),
    ([["state", "=", "sale"]], [["state", "=", "sale"]]),
    (["|", ["name", "ilike", "arc"], ["ref", "=", "A1"]], ["|", ["name", "ilike", "arc"], ["ref", "=", "A1"]]),
    ("[('name', 'ilike', 'x'), ('active', '=', True)]", [["name", "ilike", "x"], ["active", "=", True]]),
    (["!", ["active", "=", True]], ["!", ["active", "=", True]]),
])
def test_parse_domain_valid(domain, expected):
    assert tools.parse_domain(domain) == expected


@pytest.mark.parametrize("domain, message", [
    ("not python", "Could not parse"),
    ("{'a': 1}", "must be a list"),
    (["|", ["name", "=", "x"]], "needs two conditions"),
    (["!"], "nothing|no condition"),
    ([["name", "="]], "Invalid domain element"),
    (["^", ["a", "=", 1]], "Unknown domain operator"),
])
def test_parse_domain_invalid(domain, message):
    with pytest.raises(tools.ToolInputError, match=message):
        tools.parse_domain(domain)


def test_domain_schema_allows_operators():
    items = tools.DOMAIN_SCHEMA["anyOf"][0]["items"]["anyOf"]
    assert {"type": "string", "enum": ["|", "&", "!"]} in items


# ── search_records / get_record ──────────────────────────────────────────────

def test_search_records_defaults_and_pagination(fake_transport, client):
    rows = [{"id": i, "display_name": f"P{i}"} for i in range(50)]
    fake_transport.handlers[("res.partner", "search_read")] = lambda ids, kw, ctx: rows
    fake_transport.handlers[("res.partner", "search_count")] = lambda ids, kw, ctx: 230
    out = call(client, "search_records", model="res.partner")
    sr = next(c for c in fake_transport.calls if c["method"] == "search_read")
    assert sr["kwargs"]["fields"] == ["display_name"] and sr["kwargs"]["limit"] == 50
    assert sr["context"]["bin_size"] is True
    assert out["total"] == 230 and out["next_offset"] == 50 and len(out["records"]) == 50


def test_search_records_skips_count_on_short_first_page(fake_transport, client):
    fake_transport.handlers[("res.partner", "search_read")] = lambda ids, kw, ctx: [{"id": 1, "display_name": "a"}]
    out = call(client, "search_records", model="res.partner", fields=["name"], limit=10)
    assert out["total"] == 1 and out["next_offset"] is None
    assert not any(c["method"] == "search_count" for c in fake_transport.calls)


def test_search_records_v2_call_and_limit_cap(fake_transport, client):
    fake_transport.handlers[("res.partner", "search_read")] = lambda ids, kw, ctx: []
    call(client, "search_records", model="res.partner", domain=[["name", "ilike", "a"]], fields=["name"], limit=10_000)
    sr = next(c for c in fake_transport.calls if c["method"] == "search_read")
    assert sr["kwargs"]["limit"] == tools.MAX_LIMIT


def test_unknown_and_related_fields_are_rejected_before_odoo(client):
    with pytest.raises(tools.ToolInputError, match="Did you mean: phone") as info:
        call(client, "search_records", model="res.partner", fields=["phonee"])
    assert "get_model_fields" in info.value.hint
    with pytest.raises(tools.ToolInputError, match="Related path"):
        call(client, "search_records", model="res.partner", fields=["company_id.name"])


def test_get_record_reports_missing_ids_and_includes_archived(fake_transport, client):
    fake_transport.handlers[("res.partner", "search_read")] = lambda ids, kw, ctx: [
        {"id": 3, "name": "b"}, {"id": 1, "name": "a"}]
    out = call(client, "get_record", model="res.partner", ids=[1, 3, 99])
    assert [r["id"] for r in out["records"]] == [1, 3]
    assert out["missing_ids"] == [99]
    sr = next(c for c in fake_transport.calls if c["method"] == "search_read")
    assert sr["context"]["active_test"] is False
    assert "image_1920" not in sr["kwargs"]["fields"] and "message_ids" not in sr["kwargs"]["fields"]


# ── Context and companies ────────────────────────────────────────────────────

def test_context_merge_order(fake_transport):
    client = make_client(fake_transport, default_context={"lang": "en_US", "tz": "UTC"})
    fake_transport.handlers[("res.partner", "search_count")] = lambda ids, kw, ctx: 1
    call(client, "search_count", model="res.partner", context={"lang": "ar_001"}, company_ids=[108, 110])
    ctx = fake_transport.calls[-1]["context"]
    assert ctx == {"lang": "ar_001", "tz": "UTC", "allowed_company_ids": [108, 110]}


def test_company_ids_must_belong_to_the_user(client):
    with pytest.raises(OdooError, match=r"Allowed ids: \[110, 111, 108, 109, 107, 1\]"):
        call(client, "search_count", model="res.partner", company_ids=[999])


def test_get_context_lists_branches(fake_transport, client):
    company_fields = {f: {"type": "char"} for f in ("name", "parent_id", "country_code", "currency_id", "vat")}
    fake_transport.handlers[("res.company", "fields_get")] = lambda ids, kw, ctx: company_fields
    fake_transport.handlers[("res.company", "search_read")] = lambda ids, kw, ctx: [
        {"id": 110, "name": "Arc De Sol", "parent_id": [108, "G+ Interiors"], "country_code": "SA",
         "currency_id": [151, "SAR"], "vat": False},
        {"id": 1, "name": "G+ Partners", "parent_id": False, "country_code": "SA",
         "currency_id": [151, "SAR"], "vat": "300000000000003"},
    ]
    fake_transport.handlers[("ir.module.module", "search_read")] = lambda ids, kw, ctx: [
        {"id": 1, "name": "sale_management", "shortdesc": "Sales"}]
    out = call(client, "get_context")
    assert out["odoo"]["transport"] == "json2" and out["odoo"]["major"] == 20
    assert out["active_company"]["id"] == 1
    arc = next(c for c in out["companies"] if c["id"] == 110)
    assert arc["is_branch"] is True and arc["parent_id"] == [108, "G+ Interiors"] and arc["currency"] == "SAR"
    assert out["apps"] == [["sale_management", "Sales"]]
    assert "UTC" in out["notes"]


# ── Metadata tools ───────────────────────────────────────────────────────────

def test_get_model_fields_table(client):
    text = call(client, "get_model_fields", model="res.partner")
    lines = text.splitlines()
    assert lines[1] == "name|label|type|required|readonly|stored|groupable|extra"
    state = next(line for line in lines if line.startswith("state|"))
    assert state.endswith("selection(draft:Draft,done:Done)")
    company = next(line for line in lines if line.startswith("company_id|"))
    assert company.endswith("many2one(res.company)")
    assert not any(line.startswith("display_name|") for line in lines)  # not stored, not searchable


def test_get_model_fields_required_skips_defaults(fake_transport, client):
    fields = {
        "name": {"type": "char", "required": True, "store": True},
        "state": {"type": "selection", "required": True, "store": True, "selection": [["a", "A"]]},
    }
    fake_transport.handlers[("sale.order", "fields_get")] = lambda ids, kw, ctx: fields
    fake_transport.handlers[("sale.order", "default_get")] = lambda ids, kw, ctx: {"state": "a"}
    text = call(client, "get_model_fields", model="sale.order", filter="required")
    assert "\nname|" in text and "\nstate|" not in text
    assert fake_transport.calls[-1]["kwargs"] == {"fields": ["name", "state"]}  # Odoo 19+ parameter name


def test_selection_cell_is_capped():
    cell = tools._selection_cell([[f"Zone/{i:03d}", f"Zone {i}"] for i in range(500)])
    assert len(cell) <= tools.SELECTION_CELL_LIMIT + 20 and "more)" in cell


def test_list_models_table(fake_transport, client):
    ir_fields = {f: {"type": "char"} for f in ("model", "name", "transient", "abstract", "explanation")}
    fake_transport.handlers[("ir.model", "fields_get")] = lambda ids, kw, ctx: ir_fields
    fake_transport.handlers[("ir.model", "search_read")] = lambda ids, kw, ctx: [
        {"id": 1, "model": "stock.quant", "name": "Quant", "explanation": "On hand | stock " + "x" * 300},
        {"id": 2, "model": "res.partner", "name": "Contact", "explanation": "false"},
    ]
    text = call(client, "list_models", search="quant")
    domain = fake_transport.calls[-1]["kwargs"]["domain"]
    assert domain[0] == "|" and ["abstract", "=", False] in domain and ["transient", "=", False] in domain
    lines = text.splitlines()
    assert lines[1] == "model|name|explanation"
    assert lines[2].startswith("stock.quant|Quant|On hand \\| stock") and lines[2].endswith("…")
    assert lines[3] == "res.partner|Contact|"


def test_model_info_methods_grouped_by_module(fake_transport, doc_sale_order):
    client = make_client(fake_transport)
    client.doc_model = lambda model: doc_sale_order
    ir_fields = {f: {"type": "char"} for f in ("model", "name", "transient", "abstract", "explanation")}
    fake_transport.handlers[("ir.model", "fields_get")] = lambda ids, kw, ctx: ir_fields
    fake_transport.handlers[("ir.model", "search_read")] = lambda ids, kw, ctx: [
        {"model": "sale.order", "name": "Sales Order", "transient": False, "abstract": False, "explanation": "Quotes"}]
    fake_transport.handlers[("sale.order", "fields_get")] = lambda ids, kw, ctx: {
        "name": {"type": "char", "string": "Order Reference", "required": True},
        "partner_id": {"type": "many2one", "relation": "res.partner", "string": "Customer", "required": True},
        "state": {"type": "selection", "string": "Status"},
    }
    fake_transport.handlers[("sale.order", "search_count")] = lambda ids, kw, ctx: 4
    out = call(client, "model_info", model="sale.order")
    assert out["counts"] == {"fields": 3, "records": 4}
    assert "partner_id many2one(res.partner) 'Customer' required" in out["key_fields"]
    methods = out["methods"]
    assert set(methods) == {"sale", "mail"}  # core and base methods are left out
    assert any(m.startswith("action_confirm() -> bool — Confirm the given quotation(s)") for m in methods["sale"])


def test_model_info_methods_unavailable_on_xmlrpc_odoo_17(fake_transport):
    client = make_client(fake_transport, version=V17)
    assert "Odoo 17.0" in client.doc_available()


# ── aggregate ────────────────────────────────────────────────────────────────

def test_aggregate_from_formatted_read_group(fake_transport, client):
    fake_transport.handlers[("res.partner", "formatted_read_group")] = lambda ids, kw, ctx: [
        {"company_id": [108, "G+ Interiors"], "state": "done", "__count": 11, "id:count_distinct": 11,
         "__extra_domain": [["company_id", "=", 108]]},
        {"company_id": False, "state": "draft", "__count": 2, "id:count_distinct": 2, "__extra_domain": []},
    ]
    out = call(client, "aggregate", model="res.partner", groupby=["company_id", "state"],
               aggregates=["__count", "id:count_distinct"])
    assert out["groups"][0] == {"keys": {"company_id": [108, "G+ Interiors"], "state": "done"}, "count": 11,
                                "values": {"id:count_distinct": 11}}
    assert out["total_groups"] == 2 and out["next_offset"] is None
    kw = fake_transport.calls[-1]["kwargs"]
    assert kw["groupby"] == ["company_id", "state"] and kw["aggregates"] == ["__count", "id:count_distinct"]


def test_aggregate_date_groups_and_domains(fake_transport, client):
    fake_transport.handlers[("res.partner", "formatted_read_group")] = lambda ids, kw, ctx: [
        {"create_date:month": ["2026-10-01 00:00:00", "October 2026"], "__count": 7,
         "__extra_domain": ["&", ["create_date", ">=", "2026-10-01"], ["create_date", "<", "2026-11-01"]]}]
    out = call(client, "aggregate", model="res.partner", groupby=["create_date:month"], include_domain=True)
    group = out["groups"][0]
    assert group["keys"] == {"create_date:month": "October 2026"}
    assert group["domain"][0] == "&"


def test_aggregate_from_legacy_read_group(fake_transport):
    client = make_client(fake_transport, version=V17)
    fake_transport.handlers[("res.partner", "read_group")] = lambda ids, kw, ctx: [
        {"company_id": [1, "YourCompany"], "date:month": "October 2026", "__count": 5, "amount_total": 125000.0,
         "__domain": [["company_id", "=", 1]]}]
    out = call(client, "aggregate", model="res.partner", groupby=["company_id"],
               aggregates=["amount_total:sum", "__count"])
    kw = fake_transport.calls[-1]["kwargs"]
    assert fake_transport.calls[-1]["method"] == "read_group"
    assert kw["lazy"] is False and kw["fields"] == ["amount_total:sum"] and kw["orderby"] is False
    assert out["groups"][0] == {"keys": {"company_id": [1, "YourCompany"]}, "count": 5,
                                "values": {"amount_total:sum": 125000.0}}


def test_aggregate_having_rejected_before_19(fake_transport):
    client = make_client(fake_transport, version=V17)
    with pytest.raises(OdooError, match="needs Odoo 19"):
        call(client, "aggregate", model="res.partner", groupby=["company_id"], having=[["__count", ">", 1]])


def test_aggregate_falls_back_when_method_missing(fake_transport, client):
    fake_transport.handlers[("res.partner", "read_group")] = lambda ids, kw, ctx: [
        {"company_id": [1, "A"], "__count": 3}]
    out = call(client, "aggregate", model="res.partner", groupby=["company_id"])
    assert out["groups"][0]["count"] == 3
    assert client._group_method == "read_group"


# ── Writes ───────────────────────────────────────────────────────────────────

def test_create_record_single_and_batch(fake_transport, client):
    fake_transport.handlers[("res.partner", "create")] = lambda ids, kw, ctx: list(range(10, 10 + len(kw["vals_list"])))
    out = call(client, "create_record", model="res.partner", values={"name": "A"}, company_ids=[108])
    assert out == {"ids": [10], "warnings": [], "id": 10}
    assert fake_transport.calls[-1]["context"]["allowed_company_ids"] == [108]
    out = call(client, "create_record", model="res.partner", values_list=[{"name": "A"}, {"name": "B"}])
    assert out["ids"] == [10, 11] and "id" not in out


def test_create_record_unknown_field_suggestion_and_readonly_warning(fake_transport, client):
    with pytest.raises(tools.ToolInputError, match="Unknown field 'phon' on res.partner. Did you mean: phone"):
        call(client, "create_record", model="res.partner", values={"phon": "1"})
    fake_transport.handlers[("res.partner", "create")] = lambda ids, kw, ctx: [5]
    out = call(client, "create_record", model="res.partner", values={"name": "A", "country_code": "SA"})
    assert out["warnings"] == ["'country_code' is readonly and not stored: the value may be ignored by Odoo"]
    assert not any(c["method"] == "create" and "phon" in str(c) for c in fake_transport.calls)


def test_binary_dict_converted_for_older_odoo(fake_transport):
    client = make_client(fake_transport, version=V17)
    fake_transport.handlers[("res.partner", "create")] = lambda ids, kw, ctx: [1]
    call(client, "create_record", model="res.partner", values={"image_1920": {"content": "QUJD", "filename": "a.png"}})
    assert fake_transport.calls[-1]["kwargs"]["vals_list"] == [{"image_1920": "QUJD"}]


def test_update_and_delete(fake_transport, client):
    fake_transport.handlers[("res.partner", "write")] = lambda ids, kw, ctx: True
    fake_transport.handlers[("res.partner", "unlink")] = lambda ids, kw, ctx: True
    assert call(client, "update_record", model="res.partner", ids=[1], values={"phone": "1"}) == {
        "ids": [1], "success": True, "warnings": []}
    assert fake_transport.calls[-1]["kwargs"] == {"vals": {"phone": "1"}} and fake_transport.calls[-1]["ids"] == [1]
    assert call(client, "delete_record", model="res.partner", ids=[1, 2]) == {"ids": [1, 2], "success": True}


# ── execute_method and positional args ───────────────────────────────────────

def test_map_positional_args_orm_table():
    no_doc = lambda: None  # noqa: E731
    assert tools.map_positional_args("res.partner", "read", [[1, 2], ["name"]], no_doc) == ([1, 2], {"fields": ["name"]})
    assert tools.map_positional_args("res.partner", "write", [[1], {"name": "x"}], no_doc) == ([1], {"vals": {"name": "x"}})
    assert tools.map_positional_args("res.partner", "search_read", [[["a", "=", 1]], ["name"], 0, 5], no_doc) == (
        None, {"domain": [["a", "=", 1]], "fields": ["name"], "offset": 0, "limit": 5})
    assert tools.map_positional_args("res.partner", "create", [{"name": "x"}], no_doc) == (None, {"vals_list": [{"name": "x"}]})


def test_map_positional_args_from_doc_signature(doc_sale_order):
    doc = lambda: doc_sale_order  # noqa: E731
    assert tools.map_positional_args("sale.order", "action_confirm", [[7]], doc) == ([7], {})
    # name_search is @api.model in the doc fixture: no ids, args bind to parameters in order
    doc_sale_order["methods"]["custom_model_method"] = {
        "signature": "(name, limit=10)", "parameters": {"name": {}, "limit": {}}, "api": ["model"],
        "model": "sale.order", "module": "sale"}
    assert tools.map_positional_args("sale.order", "custom_model_method", ["abc", 3], doc) == (
        None, {"name": "abc", "limit": 3})
    # keyword-only parameters cannot be bound positionally
    with pytest.raises(tools.ToolInputError, match="could not be mapped"):
        tools.map_positional_args("sale.order", "message_post", [[1], "hello"], doc)


def test_map_positional_args_unknown_method():
    with pytest.raises(tools.ToolInputError, match="pass named `kwargs`"):
        tools.map_positional_args("sale.order", "mystery", [1], lambda: None)


def test_execute_method_json2_named_and_legacy(fake_transport, client):
    fake_transport.handlers[("sale.order", "action_confirm")] = lambda ids, kw, ctx: True
    assert call(client, "execute_method", model="sale.order", method="action_confirm", ids=[4]) == {"result": True}
    assert fake_transport.calls[-1]["ids"] == [4]
    fake_transport.handlers[("res.partner", "read")] = lambda ids, kw, ctx: [{"id": 1, "name": "A"}]
    out = call(client, "execute_method", model="res.partner", method="read", args=[[1], ["name"]])
    assert out == {"result": [{"id": 1, "name": "A"}]}
    assert fake_transport.calls[-1]["ids"] == [1] and fake_transport.calls[-1]["kwargs"] == {"fields": ["name"]}


def test_execute_method_xmlrpc_passes_args_through():
    t = FakeTransport(mode="xmlrpc", handlers=default_handlers())
    t.handlers[("res.partner", "read")] = lambda args, kw, ctx: [{"id": 1}]
    client = make_client(t, version=V17)
    out = call(client, "execute_method", model="res.partner", method="read", args=[[1], ["name"]],
               kwargs={"load": None})
    assert out == {"result": [{"id": 1}]}
    assert t.calls[-1]["args"] == [[1], ["name"]] and t.calls[-1]["kwargs"] == {"load": None}


def test_execute_method_none_and_private(fake_transport, client):
    fake_transport.handlers[("res.partner", "noop")] = lambda ids, kw, ctx: None
    assert call(client, "execute_method", model="res.partner", method="noop") == {"result": None}
    with pytest.raises(tools.ToolInputError, match="private"):
        call(client, "execute_method", model="res.partner", method="_compute_x")


def test_tool_annotations_complete():
    names = {t["name"] for t in tools.TOOLS}
    assert len(names) == 13
    for t in tools.TOOLS:
        assert t["title"] and t["annotations"]["openWorldHint"] is False
        assert set(t["annotations"]) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
        assert t["annotations"]["readOnlyHint"] == (t["name"] not in tools.WRITE_TOOLS)
        if t["name"] != "get_context":
            assert "company_ids" in t["inputSchema"]["properties"]
