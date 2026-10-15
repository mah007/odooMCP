"""MCP tool definitions (plain dicts) and handlers.

Handlers are synchronous (they run in a worker thread) and only use OdooClient, so they
work the same over XML-RPC and JSON-2. They return a dict/list (sent as compact JSON) or
a str (sent as-is, used for pipe tables).
"""

import ast
import difflib
import os
import re
import time
from typing import Any, Callable

from src.mcp import shaping
from src.mcp.odoo_client import OdooClient
from src.mcp.transport.base import OdooError

MAX_LIMIT = int(os.environ.get("MCP_MAX_LIMIT", "500"))
MAX_GET_IDS = 100
MAX_BINARY_RECORDS = 5
MAX_CREATE = 500
EXPLANATION_LIMIT = 160
SELECTION_CELL_LIMIT = 200
CORE_METHOD_MODELS = ("core", "base")

INSTRUCTIONS = """You are connected to an Odoo ERP database through odoo-mcp-server.
- Start by calling get_context once: it tells you the Odoo version, the user, the companies and
  branches (with ids), the language and the time zone.
- Before searching or writing a model you have not used yet, call get_model_fields for it
  (filter="required" before creating records). Use list_models(search=...) to find a model.
- Always pass `fields` to search_records and keep `limit` small. For counts, sums or per-group
  figures use search_count or aggregate, never fetch all records.
- Domains are lists of [field, operator, value]; prefix '|', '&' or '!' for OR / AND / NOT.
- Use name_search to turn a name into an id before setting many2one values.
- Multi-company: pass company_ids; the first id is the company new records are created in.
- Archived records are hidden unless context {"active_test": false}.
- Datetimes are UTC; convert only when displaying. Always state the currency of amounts.
- Binary fields are summarised; set include_binary only when you need the file itself.
- Write tools change real data: double-check the model, ids and values before calling them."""

CONTEXT_NOTES = (
    "Datetimes are UTC ('YYYY-MM-DD HH:MM:SS'); dates are plain dates. Convert to the user's "
    "time zone only for display. Monetary values: always state the currency."
)


class ToolInputError(Exception):
    """Bad arguments: reported to the model as an isError result so it can correct itself."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


# ── Shared schema pieces ─────────────────────────────────────────────────────

COMMON_PROPERTIES: dict[str, Any] = {
    "company_ids": {
        "type": "array", "items": {"type": "integer"},
        "description": "Companies to work in. The first is the active company: new records are created there "
        "and company-dependent values are read for it. Default: the connection's default context, else all of "
        "the user's companies with the user's default company active. See get_context for ids.",
    },
    "context": {
        "type": "object",
        "description": "Extra Odoo context, e.g. {\"lang\": \"ar_001\"} for Arabic names, "
        "{\"active_test\": false} to include archived records.",
    },
}

DOMAIN_SCHEMA: dict[str, Any] = {
    "description": "Odoo domain: a list of [field, operator, value] conditions, optionally prefixed by '|', '&' "
    "or '!' in Polish notation, e.g. [[\"state\",\"=\",\"sale\"]] or [\"|\",[\"name\",\"ilike\",\"arc\"],"
    "[\"ref\",\"=\",\"A1\"]]. Dotted paths such as partner_id.country_id.code are allowed in domains. "
    "A Python-literal string is also accepted.",
    "anyOf": [
        {"type": "array", "items": {"anyOf": [
            {"type": "string", "enum": ["|", "&", "!"]},
            {"type": "array", "minItems": 3, "maxItems": 3},
        ]}},
        {"type": "string"},
    ],
    "default": [],
}

MODEL = {"type": "string", "description": "Technical model name, e.g. res.partner or sale.order"}
IDS = {"type": "array", "items": {"type": "integer"}, "description": "Record ids"}
FIELDS = {"type": "array", "items": {"type": "string"}, "description": "Technical field names (see get_model_fields)"}
INCLUDE_BINARY = {
    "type": "boolean", "default": False,
    "description": "Return file/image content instead of a {binary, size} summary (max 5 records).",
}
FULL_TEXT = {
    "type": "boolean", "default": False,
    "description": "Return long text and HTML fields in full instead of cut to 2000 characters.",
}


def _annotations(read_only: bool, destructive: bool, idempotent: bool) -> dict:
    return {
        "readOnlyHint": read_only, "destructiveHint": destructive,
        "idempotentHint": idempotent, "openWorldHint": False,
    }


def _schema(properties: dict, required: list[str] | None = None, common: bool = True) -> dict:
    props = dict(properties)
    if common:
        props.update(COMMON_PROPERTIES)
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


READ_ONLY = _annotations(True, False, True)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_context",
        "title": "Get Odoo context",
        "description": "Call this once at the start: returns the Odoo version and transport, the user (language, "
        "time zone), the active company, all allowed companies and branches with ids, and installed apps.",
        "inputSchema": _schema({}),
        "annotations": READ_ONLY,
        "outputSchema": {
            "type": "object",
            "properties": {
                "odoo": {"type": "object"}, "user": {"type": "object"},
                "active_company": {"type": ["object", "null"]},
                "companies": {"type": "array"}, "apps": {"type": "array"}, "notes": {"type": "string"},
            },
            "required": ["odoo", "user", "companies"],
        },
    },
    {
        "name": "list_models",
        "title": "List models",
        "description": "List Odoo models as a model|name|explanation table. Pass `search` (matched against the "
        "technical and display names) to find a model, e.g. search='invoice'.",
        "inputSchema": _schema({
            "search": {"type": "string", "description": "Substring to look for in the model or its name"},
            "include_transient": {"type": "boolean", "default": False, "description": "Include wizards"},
            "include_abstract": {"type": "boolean", "default": False, "description": "Include abstract models"},
        }),
        "annotations": READ_ONLY,
    },
    {
        "name": "get_model_fields",
        "title": "Get model fields",
        "description": "Field list of a model as a pipe table (name|label|type|required|readonly|stored|groupable|extra). "
        "filter='required' lists the fields you must set when creating a record (fields with defaults are left out). "
        "`extra` shows the related model, selection values, currency field and translate/company_dependent flags.",
        "inputSchema": _schema({
            "model": MODEL,
            "fields": {**FIELDS, "description": "Only these fields"},
            "filter": {
                "type": "string", "enum": ["default", "required", "stored", "writable", "all"], "default": "default",
                "description": "default: stored or searchable fields; required: required without a default; "
                "stored; writable: not readonly; all",
            },
            "include_help": {"type": "boolean", "default": False, "description": "Add the field help text"},
        }, ["model"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "model_info",
        "title": "Model information",
        "description": "Purpose of a model, its field and record counts, its key fields and (Odoo 19+) its public "
        "methods grouped by module, with signatures. Use it to find methods for execute_method.",
        "inputSchema": _schema({
            "model": MODEL,
            "include_methods": {"type": "boolean", "default": True},
            "include_core_methods": {
                "type": "boolean", "default": False,
                "description": "Also list generic ORM methods (read, write, search_read, web_*…)",
            },
        }, ["model"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "search_records",
        "title": "Search records",
        "description": "Search records of a model. Returns {records, total, next_offset}. By default only display_name "
        "is returned; pass `fields` with the technical names you need (see get_model_fields). Results are paginated "
        "(default 50, max 500): use offset=next_offset for more. For counts, sums or per-group figures, use "
        "search_count or aggregate instead of fetching records. Related paths like partner_id.name are not allowed "
        "in `fields` (read the related model instead) but are allowed in `domain`.",
        "inputSchema": _schema({
            "model": MODEL,
            "domain": DOMAIN_SCHEMA,
            "fields": {**FIELDS, "description": "Fields to return (default: display_name; id is always included)"},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "description": f"Max records (max {MAX_LIMIT})"},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
            "order": {"type": "string", "description": "Sort order, e.g. 'date_order desc, id'"},
            "include_binary": INCLUDE_BINARY,
            "full_text": FULL_TEXT,
        }, ["model"]),
        "annotations": READ_ONLY,
        "outputSchema": {
            "type": "object",
            "properties": {
                "records": {"type": "array", "items": {"type": "object"}},
                "total": {"type": "integer"}, "offset": {"type": "integer"}, "limit": {"type": "integer"},
                "next_offset": {"type": ["integer", "null"]},
                "truncated": {"type": "boolean"}, "note": {"type": "string"},
            },
            "required": ["records", "total", "offset", "limit", "next_offset"],
        },
    },
    {
        "name": "search_count",
        "title": "Count records",
        "description": "Count the records of a model that match a domain.",
        "inputSchema": _schema({"model": MODEL, "domain": DOMAIN_SCHEMA}, ["model"]),
        "annotations": READ_ONLY,
        "outputSchema": {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]},
    },
    {
        "name": "get_record",
        "title": "Get records by id",
        "description": "Read records by id (max 100). Without `fields` it returns every field except binaries, "
        "one2many lists and chatter/activity fields. Ids that do not exist (or are not readable) are listed in "
        "missing_ids. Archived records are included.",
        "inputSchema": _schema({
            "model": MODEL,
            "ids": {**IDS, "maxItems": MAX_GET_IDS},
            "fields": FIELDS,
            "include_binary": INCLUDE_BINARY,
            "full_text": FULL_TEXT,
        }, ["model", "ids"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "name_search",
        "title": "Find records by name",
        "description": "Resolve a name (customer, product, company, account…) to record ids. Use this before writing "
        "many2one values.",
        "inputSchema": _schema({
            "model": MODEL,
            "name": {"type": "string", "description": "Text to look for"},
            "domain": DOMAIN_SCHEMA,
            "operator": {"type": "string", "default": "ilike", "description": "ilike, =, like, =ilike…"},
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
        }, ["model", "name"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "aggregate",
        "title": "Aggregate records",
        "description": "Totals, averages and counts grouped by fields: use this for any 'how many / how much / per …' "
        "question instead of fetching records. Example: groupby=['company_id','date:month'], "
        "aggregates=['amount_total:sum','__count'].",
        "inputSchema": _schema({
            "model": MODEL,
            "domain": DOMAIN_SCHEMA,
            "groupby": {
                "type": "array", "items": {"type": "string"},
                "description": "Fields to group by; dates as 'date_field:day|week|month|quarter|year'. Empty: one total.",
            },
            "aggregates": {
                "type": "array", "items": {"type": "string"}, "default": ["__count"],
                "description": "'field:sum|avg|min|max|count_distinct|array_agg' or '__count'",
            },
            "having": {
                "type": "array",
                "description": "Odoo 19+ only: domain over aggregates, e.g. [[\"amount_total:sum\",\">\",1000]]",
            },
            "order": {"type": "string", "description": "e.g. 'amount_total:sum desc'"},
            "limit": {"type": "integer", "default": 100, "minimum": 1, "description": f"Max groups (max {MAX_LIMIT})"},
            "offset": {"type": "integer", "default": 0, "minimum": 0},
            "include_domain": {
                "type": "boolean", "default": False, "description": "Add each group's domain (to drill down)",
            },
        }, ["model"]),
        "annotations": READ_ONLY,
        "outputSchema": {
            "type": "object",
            "properties": {
                "groups": {"type": "array", "items": {"type": "object"}},
                "total_groups": {"type": ["integer", "null"]},
                "next_offset": {"type": ["integer", "null"]},
                "truncated": {"type": "boolean"}, "note": {"type": "string"},
            },
            "required": ["groups"],
        },
    },
    {
        "name": "create_record",
        "title": "Create records",
        "description": "Create one record (`values`) or several (`values_list`, max 500). Unknown field names are "
        "rejected with suggestions before anything is sent to Odoo. Returns {ids, warnings}.",
        "inputSchema": _schema({
            "model": MODEL,
            "values": {"type": "object", "description": "Field values for one new record"},
            "values_list": {
                "type": "array", "items": {"type": "object"}, "maxItems": MAX_CREATE,
                "description": "Field values for several new records",
            },
        }, ["model"]),
        "annotations": _annotations(False, False, False),
    },
    {
        "name": "update_record",
        "title": "Update records",
        "description": "Write the same `values` to the records `ids`. Returns {ids, success, warnings}.",
        "inputSchema": _schema({"model": MODEL, "ids": IDS, "values": {"type": "object"}}, ["model", "ids", "values"]),
        "annotations": _annotations(False, True, True),
    },
    {
        "name": "delete_record",
        "title": "Delete records",
        "description": "Delete (unlink) the records `ids`. This cannot be undone; prefer archiving "
        "(update active=false) when the model has an `active` field.",
        "inputSchema": _schema({"model": MODEL, "ids": IDS}, ["model", "ids"]),
        "annotations": _annotations(False, True, True),
    },
    {
        "name": "execute_method",
        "title": "Call a model method",
        "description": "Call a public method of a model (e.g. action_confirm on sale.order, button_validate on "
        "stock.picking). Pass record ids in `ids` and named arguments in `kwargs`. model_info lists a model's "
        "methods on Odoo 19+.",
        "inputSchema": _schema({
            "model": MODEL,
            "method": {"type": "string", "description": "Public method name"},
            "ids": {**IDS, "description": "Records to call the method on (omit for @api.model methods)"},
            "kwargs": {"type": "object", "default": {}, "description": "Named arguments"},
            "args": {
                "type": "array", "default": [],
                "description": "Legacy positional arguments (XML-RPC style, first element = ids for record methods). "
                "Prefer ids + kwargs.",
            },
        }, ["model", "method"]),
        "annotations": _annotations(False, True, False),
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}
WRITE_TOOLS = frozenset({"create_record", "update_record", "delete_record", "execute_method"})
STRUCTURED_TOOLS = frozenset(t["name"] for t in TOOLS if "outputSchema" in t)


# ── Argument validation ──────────────────────────────────────────────────────

def _coerce(value: Any, schema: dict, path: str) -> Any:
    if "anyOf" in schema:
        errors = []
        for option in schema["anyOf"]:
            try:
                return _coerce(value, option, path)
            except ToolInputError as exc:
                errors.append(exc.message)
        raise ToolInputError(f"`{path}` has an invalid value: {errors[0]}")
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolInputError(f"`{path}` must be a string")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolInputError(f"`{path}` must be one of {schema['enum']}")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, str, float)):
            raise ToolInputError(f"`{path}` must be an integer")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ToolInputError(f"`{path}` must be an integer") from None
    elif expected == "boolean":
        if isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"
        if not isinstance(value, bool):
            raise ToolInputError(f"`{path}` must be true or false")
    elif expected == "object":
        if isinstance(value, str):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                pass
        if not isinstance(value, dict):
            raise ToolInputError(f"`{path}` must be an object")
    elif expected == "array":
        if isinstance(value, (int, str)) and schema.get("items", {}).get("type") in ("integer", "string"):
            value = [value]  # a single id / field name
        if not isinstance(value, (list, tuple)):
            raise ToolInputError(f"`{path}` must be an array")
        value = list(value)
        items = schema.get("items")
        if items and items.get("type") in ("integer", "string", "object"):
            value = [_coerce(v, items, f"{path}[{i}]") for i, v in enumerate(value)]
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ToolInputError(f"`{path}` accepts at most {schema['maxItems']} items")
    return value


def validate_arguments(tool: dict, arguments: dict) -> dict:
    schema = tool["inputSchema"]
    props = schema.get("properties", {})
    missing = [r for r in schema.get("required", []) if arguments.get(r) in (None, "")]
    if missing:
        raise ToolInputError(f"Missing required argument(s): {', '.join(missing)}")
    out = dict(arguments)
    for name, value in arguments.items():
        if name in props and value is not None:
            out[name] = _coerce(value, props[name], name)
    return out


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_domain(value: Any) -> list:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value.strip())
        except (ValueError, SyntaxError) as exc:
            raise ToolInputError(f"Could not parse the domain string: {exc}") from None
    if not isinstance(value, (list, tuple)):
        raise ToolInputError("The domain must be a list of conditions")
    domain: list = []
    stack = 0
    for item in value:
        if isinstance(item, str):
            if item not in ("|", "&", "!"):
                raise ToolInputError(f"Unknown domain operator {item!r}; use '|', '&' or '!'")
            domain.append(item)
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            domain.append(list(item))
        else:
            raise ToolInputError(
                f"Invalid domain element {item!r}: expected [field, operator, value] or '|', '&', '!'",
                "Example: [\"|\", [\"name\", \"ilike\", \"arc\"], [\"ref\", \"=\", \"A1\"]]",
            )
    for item in reversed(domain):  # Polish notation arity check
        if isinstance(item, list):
            stack += 1
        elif item == "!":
            if stack < 1:
                raise ToolInputError("Domain operator '!' has no condition to negate")
        else:
            if stack < 2:
                raise ToolInputError(f"Domain operator {item!r} needs two conditions after it")
            stack -= 1
    return domain


def _suggest(name: str, choices: list[str]) -> str:
    close = difflib.get_close_matches(name, choices, n=3, cutoff=0.6)
    return f" Did you mean: {', '.join(close)}?" if close else ""


def check_fields(meta: dict, model: str, fields: list[str]) -> None:
    for name in fields:
        if "." in name:
            raise ToolInputError(
                f"Related path '{name}' is not allowed in `fields`.",
                f"Read '{name.split('.')[0]}' (an id) and query the related model, or use the path in `domain`.",
            )
        if name not in meta:
            raise ToolInputError(
                f"Unknown field '{name}' on {model}.{_suggest(name, list(meta))}",
                f"call get_model_fields for {model}",
            )


def _clamp(value: Any, default: int, maximum: int) -> int:
    if not value or int(value) <= 0:
        return default
    return min(int(value), maximum)


def _ids(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, (int, str)):
        raw = [raw]
    try:
        return [int(i) for i in raw]
    except (TypeError, ValueError):
        raise ToolInputError("`ids` must be a list of integers") from None


def _ctx(client: OdooClient, a: dict) -> dict:
    return client.build_context(a.get("context"), a.get("company_ids"))


def _precheck_values(client: OdooClient, model: str, vals_list: list[dict], ctx: dict) -> list[str]:
    meta = client.fields_get(model, ctx)
    warnings: list[str] = []
    for vals in vals_list:
        if not isinstance(vals, dict):
            raise ToolInputError("Each set of values must be an object of field: value")
        for name, value in list(vals.items()):
            if name not in meta:
                raise ToolInputError(
                    f"Unknown field '{name}' on {model}.{_suggest(name, list(meta))}",
                    f"call get_model_fields for {model} (filter='writable')",
                )
            info = meta[name]
            if info.get("readonly") and not info.get("store", True):
                msg = f"'{name}' is readonly and not stored: the value may be ignored by Odoo"
                if msg not in warnings:
                    warnings.append(msg)
            if info.get("type") in shaping.BINARY_TYPES and isinstance(value, dict) and client.version.major < 20:
                vals[name] = value.get("content") or False  # {content, filename} is an Odoo 20 form
    return warnings


# ── Handlers ─────────────────────────────────────────────────────────────────

def get_context(client: OdooClient, a: dict) -> dict:
    ctx = _ctx(client, a)
    key = shaping.dumps(ctx)
    cached = client.context_cache.get(key)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]

    version = client.version
    user = client.user_info()
    company_ids = user["company_ids"]
    company_fields = [f for f in ("name", "parent_id", "country_code", "currency_id", "vat")
                      if client.has_field("res.company", f)]
    rows = client.search_read(
        "res.company", [["id", "in", company_ids]], company_fields,
        context={"allowed_company_ids": company_ids},
    )
    companies = []
    for c in rows:
        parent = c.get("parent_id") or None
        companies.append({
            "id": c["id"], "name": c["name"], "parent_id": parent, "is_branch": bool(parent),
            "country_code": c.get("country_code") or None,
            "currency": (c.get("currency_id") or [None, None])[1],
            "vat": c.get("vat") or None,
        })
    active_id = (ctx.get("allowed_company_ids") or [user["company_id"][0]])[0]
    active = next((c for c in companies if c["id"] == active_id), None)
    apps = client.search_read(
        "ir.module.module", [["state", "=", "installed"], ["application", "=", True]], ["name", "shortdesc"],
        order="sequence, name",
    )
    odoo: dict[str, Any] = {
        "version": version.raw, "major": version.major, "transport": client.mode,
        "database": client.config.database, "url": client.config.url,
    }
    if client.mode_note:
        odoo["note"] = client.mode_note
    result = {
        "odoo": odoo,
        "user": {
            "id": user["id"], "name": user["name"], "login": user["login"],
            "lang": ctx.get("lang") or user.get("lang"), "tz": ctx.get("tz") or user.get("tz"),
        },
        "active_company": active and {k: active[k] for k in ("id", "name", "country_code", "currency")},
        "companies": companies,
        "apps": [[m["name"], m["shortdesc"]] for m in apps],
        "notes": CONTEXT_NOTES,
    }
    if client.config.default_context:
        result["default_context"] = client.config.default_context
    client.context_cache[key] = (time.monotonic(), result)
    return result


def list_models(client: OdooClient, a: dict) -> str:
    ctx = _ctx(client, a)
    include_transient = a.get("include_transient", a.get("transient", False))
    domain: list = []
    if not include_transient:
        domain.append(["transient", "=", False])
    has_abstract = client.has_field("ir.model", "abstract")
    has_explanation = client.has_field("ir.model", "explanation")
    if has_abstract and not a.get("include_abstract"):
        domain.append(["abstract", "=", False])
    search = (a.get("search") or "").strip()
    if search:
        domain = ["|", ["model", "ilike", search], ["name", "ilike", search]] + domain
    fields = ["model", "name"] + (["explanation"] if has_explanation else [])
    rows = client.search_read("ir.model", domain, fields, order="model", context=ctx)
    table_rows = []
    for r in rows:
        explanation = r.get("explanation")
        if explanation in (False, None, "false"):
            explanation = ""
        explanation = " ".join(str(explanation).split())
        if len(explanation) > EXPLANATION_LIMIT:
            explanation = explanation[: EXPLANATION_LIMIT - 1] + "…"
        table_rows.append([r["model"], r["name"], explanation] if has_explanation else [r["model"], r["name"]])
    header = ["model", "name", "explanation"] if has_explanation else ["model", "name"]
    note = f"# {len(rows)} models" + (f" matching '{search}'" if search else "; pass search=... to filter")
    if not rows:
        return note + ". Try a shorter search or include_transient=true."
    return note + "\n" + shaping.pipe_table(header, table_rows)


def _selection_cell(selection: list) -> str:
    keys = [str(k) for k, _ in selection]
    with_labels = "selection(" + ",".join(f"{k}:{v}" for k, v in selection) + ")"
    if len(with_labels) <= SELECTION_CELL_LIMIT:
        return with_labels
    out = "selection("
    for i, k in enumerate(keys):
        if len(out) + len(k) + 20 > SELECTION_CELL_LIMIT:
            return out.rstrip(",") + f",…+{len(keys) - i} more)"
        out += k + ","
    return out.rstrip(",") + ")"


def _field_extra(info: dict) -> str:
    parts = []
    if info.get("relation"):
        parts.append(f"{info['type']}({info['relation']})")
    if info.get("type") == "selection" and isinstance(info.get("selection"), list):
        parts.append(_selection_cell(info["selection"]))
    if info.get("currency_field"):
        parts.append(f"currency:{info['currency_field']}")
    if info.get("company_dependent"):
        parts.append("company_dependent")
    if info.get("translate"):
        parts.append("translate")
    return " ".join(parts)


def get_model_fields(client: OdooClient, a: dict) -> str:
    model = a["model"]
    ctx = _ctx(client, a)
    meta = client.fields_get(model, ctx)
    flt = a.get("filter") or "default"
    names = list(meta)
    if a.get("fields"):
        for name in a["fields"]:
            if name not in meta:
                raise ToolInputError(f"Unknown field '{name}' on {model}.{_suggest(name, names)}")
        names = list(a["fields"])
        flt = "all" if flt == "default" else flt
    yn = lambda v: "y" if v else "n"  # noqa: E731
    if flt == "default":
        names = [n for n in names if meta[n].get("store") or meta[n].get("searchable")]
    elif flt == "stored":
        names = [n for n in names if meta[n].get("store")]
    elif flt == "writable":
        names = [n for n in names if not meta[n].get("readonly")]
    elif flt == "required":
        required = [n for n in names if meta[n].get("required")]
        defaults = client.default_get(model, required, ctx) if required else {}
        names = [n for n in required if n not in defaults]
    names.sort()
    header = ["name", "label", "type", "required", "readonly", "stored", "groupable", "extra"]
    if a.get("include_help"):
        header.append("help")
    rows = []
    for n in names:
        info = meta[n]
        row = [
            n, info.get("string"), info.get("type"), yn(info.get("required")), yn(info.get("readonly")),
            yn(info.get("store")), yn(info.get("groupable", info.get("store"))), _field_extra(info),
        ]
        if a.get("include_help"):
            row.append(info.get("help") or "")
        rows.append(row)
    note = f"# {model}: {len(rows)} of {len(meta)} fields (filter={flt}); y=yes n=no"
    if flt == "required":
        note += "; fields with a default value are left out"
    return note + "\n" + shaping.pipe_table(header, rows)


def _first_doc_line(doc: str | None) -> str:
    if not doc:
        return ""
    text = shaping.html_to_text(doc)
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= 140 else line[:139] + "…"


def model_info(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    ctx = _ctx(client, a)
    ir_fields = ["model", "name", "transient"] + [
        f for f in ("abstract", "explanation") if client.has_field("ir.model", f)
    ]
    rows = client.search_read("ir.model", [["model", "=", model]], ir_fields, limit=1, context=ctx)
    if not rows:
        raise ToolInputError(f"Model '{model}' not found.", "use list_models(search=...) to find the technical name")
    row = rows[0]
    meta = client.fields_get(model, ctx)
    result: dict[str, Any] = {"model": model, "name": row["name"]}
    explanation = row.get("explanation")
    if explanation and explanation != "false":
        result["explanation"] = explanation
    if row.get("transient"):
        result["transient"] = True
    if row.get("abstract"):
        result["abstract"] = True
    try:
        records = client.search_count(model, [], ctx) if not row.get("abstract") else None
    except OdooError:
        records = None
    result["counts"] = {"fields": len(meta), "records": records}
    key = [n for n, f in meta.items() if f.get("required") and n != "id"]
    key += [n for n in ("name", "state", "company_id", "active", "currency_id") if n in meta and n not in key]
    result["key_fields"] = [
        f"{n} {meta[n]['type']}" + (f"({meta[n]['relation']})" if meta[n].get("relation") else "")
        + f" '{meta[n].get('string')}'" + (" required" if meta[n].get("required") else "")
        for n in key
    ]
    if a.get("include_methods", True):
        result["methods"] = _methods(client, model, bool(a.get("include_core_methods")))
    return result


def _methods(client: OdooClient, model: str, include_core: bool) -> Any:
    reason = client.doc_available()
    if reason:
        return reason
    try:
        doc = client.doc_model(model)
    except OdooError as exc:
        if exc.status in (401, 403, 404):
            return ("not available (the user needs the Technical Documentation group, or the api_doc module "
                    f"is not installed): {exc.short_name}")
        raise
    grouped: dict[str, list[str]] = {}
    for name, m in sorted(doc.get("methods", {}).items()):
        if not include_core and m.get("model") in CORE_METHOD_MODELS:
            continue
        line = f"{name}{m.get('signature', '()')}"
        if "model" in (m.get("api") or []):
            line += " [model]"
        first = _first_doc_line(m.get("doc"))
        if first:
            line += f" — {first}"
        grouped.setdefault(m.get("module") or "core", []).append(line)
    return grouped


def search_records(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    ctx = _ctx(client, a)
    domain = parse_domain(a.get("domain"))
    fields = a.get("fields") or ["display_name"]
    meta = client.fields_get(model, ctx)
    check_fields(meta, model, fields)
    include_binary = bool(a.get("include_binary"))
    limit = _clamp(a.get("limit"), 50, MAX_LIMIT)
    note = None
    if include_binary and limit > MAX_BINARY_RECORDS:
        limit = MAX_BINARY_RECORDS
        note = f"include_binary is limited to {MAX_BINARY_RECORDS} records per call"
    offset = max(int(a.get("offset") or 0), 0)
    records = client.search_read(model, domain, fields, offset, limit, a.get("order"), ctx, include_binary)
    if offset == 0 and len(records) < limit:
        total = len(records)
    else:
        total = client.search_count(model, domain, ctx)
    records = shaping.shape_records(records, meta, include_binary=include_binary, full_text=bool(a.get("full_text")))
    end = offset + len(records)
    payload: dict[str, Any] = {
        "records": records, "total": total, "offset": offset, "limit": limit,
        "next_offset": end if end < total else None,
    }
    if note:
        payload["note"] = note
    payload = shaping.guard_records(payload)
    if payload.get("truncated"):
        payload["next_offset"] = offset + len(payload["records"])
    return payload


def search_count(client: OdooClient, a: dict) -> dict:
    ctx = _ctx(client, a)
    return {"count": client.search_count(a["model"], parse_domain(a.get("domain")), ctx)}


def get_record(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    ids = _ids(a.get("ids"))
    if not ids:
        raise ToolInputError("`ids` is empty")
    if len(ids) > MAX_GET_IDS:
        raise ToolInputError(f"get_record takes at most {MAX_GET_IDS} ids per call", "split the ids into batches")
    include_binary = bool(a.get("include_binary"))
    if include_binary and len(ids) > MAX_BINARY_RECORDS:
        raise ToolInputError(f"include_binary is limited to {MAX_BINARY_RECORDS} records per call")
    ctx = _ctx(client, a)
    meta = client.fields_get(model, ctx)
    fields = a.get("fields") or shaping.compact_default_fields(meta)
    check_fields(meta, model, fields)
    rows = client.search_read(
        model, [["id", "in", ids]], fields, context={**ctx, "active_test": False}, include_binary=include_binary,
    )
    by_id = {r["id"]: r for r in rows}
    ids = list(dict.fromkeys(ids))
    records = [by_id[i] for i in ids if i in by_id]
    records = shaping.shape_records(records, meta, include_binary=include_binary, full_text=bool(a.get("full_text")))
    payload: dict[str, Any] = {"records": records}
    missing = [i for i in ids if i not in by_id]
    if missing:
        payload["missing_ids"] = missing
        payload["note"] = "missing_ids do not exist, were deleted, or are not readable by the connection's user"
    return shaping.guard_records(payload)


def name_search(client: OdooClient, a: dict) -> list:
    ctx = _ctx(client, a)
    limit = _clamp(a.get("limit"), 10, 100)
    rows = client.name_search(
        a["model"], a.get("name") or "", parse_domain(a.get("domain")), a.get("operator") or "ilike", limit, ctx,
    )
    return [{"id": r[0], "display_name": r[1]} for r in rows]


_AGG_RE = re.compile(r"^(__count|[\w.]+:\w+)$")


def _group_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
        return value[1]  # date groups come back as [start, label] in Odoo 19+
    return value


def normalize_groups(rows: list[dict], groupby: list[str], aggregates: list[str], include_domain: bool) -> list[dict]:
    groups = []
    for row in rows:
        keys = {g: _group_value(row.get(g, row.get(g.split(":")[0]))) for g in groupby}
        count = row.get("__count")
        if count is None and groupby:
            count = row.get(f"{groupby[0].split(':')[0]}_count")
        values = {}
        for agg in aggregates:
            if agg == "__count":
                continue
            values[agg] = row[agg] if agg in row else row.get(agg.split(":")[0])
        group: dict[str, Any] = {"keys": keys, "count": count, "values": values}
        if include_domain:
            group["domain"] = row.get("__extra_domain", row.get("__domain"))
        groups.append(group)
    return groups


def aggregate(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    ctx = _ctx(client, a)
    domain = parse_domain(a.get("domain"))
    groupby = list(a.get("groupby") or [])
    aggregates = list(a.get("aggregates") or ["__count"])
    for agg in aggregates:
        if not _AGG_RE.match(agg):
            raise ToolInputError(f"Invalid aggregate '{agg}': use 'field:sum' (or avg, min, max, count_distinct, "
                                 "array_agg) or '__count'")
    meta = client.fields_get(model, ctx)
    for spec in groupby + [x for x in aggregates if x != "__count"]:
        root = spec.split(":")[0].split(".")[0]
        if root not in meta:
            raise ToolInputError(f"Unknown field '{root}' on {model}.{_suggest(root, list(meta))}",
                                 f"call get_model_fields for {model}")
    having = parse_domain(a.get("having")) if a.get("having") else None
    limit = _clamp(a.get("limit"), 100, MAX_LIMIT)
    offset = max(int(a.get("offset") or 0), 0)
    rows = client.group(
        model, domain, groupby, aggregates, having=having, offset=offset, limit=limit,
        order=a.get("order"), context=ctx,
    )
    groups = normalize_groups(rows, groupby, aggregates, bool(a.get("include_domain")))
    more = len(groups) >= limit
    payload: dict[str, Any] = {
        "groups": groups,
        "total_groups": None if more else offset + len(groups),
        "next_offset": offset + len(groups) if more else None,
    }
    return shaping.guard_records(payload, "groups")


def create_record(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    if a.get("values") is not None and a.get("values_list"):
        raise ToolInputError("Pass either `values` or `values_list`, not both")
    single = a.get("values")
    vals_list = [single] if single is not None else a.get("values_list")
    if not vals_list:
        raise ToolInputError("Missing `values` (one record) or `values_list` (several)")
    if len(vals_list) > MAX_CREATE:
        raise ToolInputError(f"values_list accepts at most {MAX_CREATE} records per call")
    ctx = _ctx(client, a)
    vals_list = [dict(v) if isinstance(v, dict) else v for v in vals_list]
    warnings = _precheck_values(client, model, vals_list, ctx)
    ids = client.create(model, vals_list, ctx)
    result: dict[str, Any] = {"ids": ids, "warnings": warnings}
    if single is not None:
        result["id"] = ids[0]
    return result


def update_record(client: OdooClient, a: dict) -> dict:
    model = a["model"]
    ids = _ids(a.get("ids"))
    if not ids:
        raise ToolInputError("`ids` is empty")
    ctx = _ctx(client, a)
    vals = dict(a["values"])
    warnings = _precheck_values(client, model, [vals], ctx)
    client.write(model, ids, vals, ctx)
    return {"ids": ids, "success": True, "warnings": warnings}


def delete_record(client: OdooClient, a: dict) -> dict:
    ids = _ids(a.get("ids"))
    if not ids:
        raise ToolInputError("`ids` is empty")
    client.unlink(a["model"], ids, _ctx(client, a))
    return {"ids": ids, "success": True}


# Parameter names of ORM methods, used to map v2 positional args on JSON-2. "ids" = the recordset.
ORM_PARAMS: dict[str, list[str]] = {
    "search_read": ["domain", "fields", "offset", "limit", "order"],
    "search": ["domain", "offset", "limit", "order"],
    "search_count": ["domain", "limit"],
    "read": ["ids", "fields", "load"],
    "write": ["ids", "vals"],
    "create": ["vals_list"],
    "unlink": ["ids"],
    "copy": ["ids", "default"],
    "fields_get": ["allfields", "attributes"],
    "name_search": ["name", "domain", "operator", "limit"],
    "formatted_read_group": ["domain", "groupby", "aggregates", "having", "offset", "limit", "order"],
    "action_archive": ["ids"],
    "action_unarchive": ["ids"],
}


def map_positional_args(
    model: str, method: str, args: list, doc_lookup: Callable[[], dict | None]
) -> tuple[list[int] | None, dict]:
    """Bind XML-RPC style positional args to JSON-2 named arguments. Returns (ids, kwargs)."""
    unmapped = ToolInputError(
        f"On Odoo 19+ pass named `kwargs` (and `ids` for record methods); positional `args` could not be "
        f"mapped for {model}.{method}."
    )
    if method in ORM_PARAMS:
        params = ORM_PARAMS[method]
        if len(args) > len(params):
            raise ToolInputError(f"{model}.{method} takes at most {len(params)} positional arguments ({', '.join(params)})")
        ids, kwargs = None, {}
        for name, value in zip(params, args):
            if name == "ids":
                ids = _ids(value)
            else:
                kwargs[name] = value
        if method == "create" and isinstance(kwargs.get("vals_list"), dict):
            kwargs["vals_list"] = [kwargs["vals_list"]]
        return ids, kwargs
    try:
        doc = doc_lookup()
    except OdooError:
        doc = None
    spec = (doc or {}).get("methods", {}).get(method)
    if not spec:
        raise unmapped
    rest = list(args)
    ids = None
    if "model" not in (spec.get("api") or []):
        if not rest:
            raise ToolInputError(f"{model}.{method} is a record method: pass the record ids in `ids`")
        ids = _ids(rest.pop(0))
    positional = [
        name for name, p in spec.get("parameters", {}).items()
        if p.get("kind", "POSITIONAL_OR_KEYWORD") in ("POSITIONAL_OR_KEYWORD", "POSITIONAL_ONLY")
    ]
    if len(rest) > len(positional):
        raise unmapped
    return ids, dict(zip(positional, rest))


def execute_method(client: OdooClient, a: dict) -> dict:
    model, method = a["model"], a["method"]
    if method.startswith("_"):
        raise ToolInputError(f"'{method}' is private; only public methods can be called")
    ctx = _ctx(client, a)
    ids = _ids(a.get("ids")) if a.get("ids") is not None else None
    kwargs = dict(a.get("kwargs") or {})
    args = list(a.get("args") or [])
    if args and client.mode == "xmlrpc":
        positional = ([ids] if ids is not None else []) + args
        if ctx:
            kwargs["context"] = {**ctx, **kwargs.get("context", {})}
        result = client.transport.call_positional(model, method, positional, kwargs)  # type: ignore[attr-defined]
    else:
        if args:
            mapped_ids, mapped_kwargs = map_positional_args(model, method, args, lambda: client.doc_model(model))
            ids = ids if ids is not None else mapped_ids
            kwargs = {**mapped_kwargs, **kwargs}
        call_ctx = {**ctx, **kwargs.pop("context", {})}
        result = client.call(model, method, ids=ids, kwargs=kwargs, context=call_ctx)
    shaped = shaping.shape_generic(result, full_text=bool(a.get("full_text")))
    return shaping.guard_any({"result": shaped})


HANDLERS: dict[str, Callable[[OdooClient, dict], Any]] = {
    "get_context": get_context,
    "list_models": list_models,
    "get_model_fields": get_model_fields,
    "model_info": model_info,
    "search_records": search_records,
    "search_count": search_count,
    "get_record": get_record,
    "name_search": name_search,
    "aggregate": aggregate,
    "create_record": create_record,
    "update_record": update_record,
    "delete_record": delete_record,
    "execute_method": execute_method,
}
