# Odoo MCP Server — Development Agenda

> This document is the single source of truth for project state and roadmap.
> Keep it updated as development progresses.

---

## Project Identity

| Field | Value |
|-------|-------|
| **Name** | odoo-mcp-server |
| **Version** | 3.0.0 |
| **Author** | Mahmoud Abdel Latif (enhanced from Václav Zeman's original) |
| **License** | MIT in `pyproject.toml` and the README, but `LICENSE` holds the GNU GPL v3 text: see Open Items |
| **Python** | 3.11+ |
| **Stack** | FastAPI · Uvicorn · SQLAlchemy/SQLite · httpx · XML-RPC · React/Vite/Tailwind admin UI |

---

## What the Project Does

An MCP server between AI agents (Claude Code, Claude, ChatGPT, n8n) and any Odoo database, from Odoo 10 to 20.

```
AI agent ──MCP over HTTP (JSON-RPC 2.0, X-API-Key / Bearer)──▶ MCP service :8000
                                                                   │
                                     auto: Odoo ≥ 19 → JSON-2 ─────┤
                                           Odoo ≤ 18 → XML-RPC ────┤
                                                                   ▼
                                                             Odoo instance
Admin UI + REST API :8001 ──▶ SQLite (connections, keys, admins, request log)
```

---

## Current Architecture (v3)

One Docker container runs two Uvicorn apps (`start.sh`) that share `data/mcp.db`.

### Module map

```
src/
├── mcp/                       MCP service (port 8000)
│   ├── app.py                 FastAPI: POST /mcp, auth (key prefix + bcrypt, cached), Origin check,
│   │                          client cache per connection (keyed by updated_at), request log
│   ├── protocol.py            JSON-RPC + MCP: version negotiation, ping, notifications (202), batches,
│   │                          tools/list (scope filter), tools/call (isError results, hints)
│   ├── tools.py               13 tool definitions (plain dicts + annotations) and handlers,
│   │                          argument checks, domain parsing, positional-args mapping for JSON-2
│   ├── shaping.py             compact JSON, binary summaries, truncation, x2many cut, size guard, pipe tables
│   ├── odoo_client.py         facade: version detection, transport choice, caches (uid, fields_get,
│   │                          context, /doc), context merging, group/default_get version handling
│   └── transport/
│       ├── base.py            Transport protocol, OdooError, MethodNotFound
│       ├── detect.py          detect_version(), select_mode()
│       ├── xmlrpc.py          XmlRpcTransport (Odoo ≤ 18, or forced)
│       └── json2.py           Json2Transport (Odoo ≥ 19)
├── controller/                Admin UI + REST API (port 8001)
│   ├── routes/connections.py  CRUD, step-by-step Test (detect → transport → auth → read user), activate
│   ├── routes/api_keys.py     create (scope), PATCH scope/name, revoke
│   ├── routes/dashboard.py    totals, per-tool count/avg size/avg time, recent logs
│   └── routes/auth.py, admins.py
└── shared/
    ├── models.py              AdminUser, OdooConnection, ApiKey, RequestLog
    └── database.py            engine, init_db() + in-place column migration (no Alembic)
frontend/src/pages/            Connections, ApiKeys, Dashboard, Settings, Setup, Login
tests/unit/                    no Odoo needed (respx for JSON-2, fake ServerProxy for XML-RPC)
tests/integration/             live, env-gated (see test_live.py docstring)
```

### Tools (13)

`get_context`, `list_models`, `get_model_fields`, `model_info`, `search_records`, `search_count`, `get_record`, `name_search`, `aggregate`, `create_record`, `update_record`, `delete_record`, `execute_method`. The names of the 10 v2 tools are frozen: Claude Code permission rules and n8n workflows refer to them.

### Configuration

- **Per connection** (admin UI): URL, database, username, credential and type, `api_mode` (auto/xmlrpc/json2), `verify_ssl`, `timeout`, `default_context`.
- **Environment:** `SECRET_KEY`, `MCP_PORT`, `CONTROLLER_PORT`, `DB_PATH`, `MCP_MAX_LIMIT`, `MCP_MAX_RESPONSE_BYTES`, `MCP_ALLOWED_ORIGINS`, `MCP_READ_KEY_BLOCKLIST`.

### Deployed instances

| Instance | Where | Odoo | Notes |
|---|---|---|---|
| Arc De Sol | `~/.local/share/odoo-mcp-arcdesol`, compose project `odoo-mcp-arcdesol`, `127.0.0.1:9110` / `:9111` | 20.0 EE sandbox | Connection stores a password, so it stays on XML-RPC until an RPC-scope API key is set |
| Alghomlas | `~/projects/Alghomlas/odoo-tools/odooMCP` | unknown | Not upgraded yet; auto-detection will pick the transport |

---

## Known Issues / Technical Debt

- [ ] Odoo 19.0 has not been tested live. The 19 behaviour comes from the Odoo 20 source; the client falls back between `formatted_read_group` and `read_group`, and between the `default_get` parameter names, at runtime.
- [ ] Odoo ≤ 18 is covered by unit tests and by forced XML-RPC on Odoo 20, not by a live ≤ 18 instance.
- [ ] `list_models` lists models the user may not be able to read (no per-model access check, to keep it to one call).
- [ ] The Fernet key is derived by truncating/padding `SECRET_KEY` (`controller/crypto.py`); changing `SECRET_KEY` makes stored credentials unreadable.
- [ ] Both services call `create_all()` at start-up; on a brand-new database they can race (the column migration itself tolerates the race).
- [ ] The request log grows without bound (no retention policy).

---

## Roadmap

### Done in v3.0.0
- [x] Dual transport (XML-RPC ≤ 18, JSON-2 ≥ 19) with auto-detection and per-connection override
- [x] AI-friendly output (pagination, small defaults, binary summaries, size guard, compact UTF-8 JSON, pipe tables)
- [x] MCP protocol compliance (versions 2024-11-05 → 2025-11-25, notifications, `isError`, annotations, structured content, batches)
- [x] Context awareness: `get_context`, `company_ids` / `context` on every tool, `default_context` per connection
- [x] New tools `get_context`, `aggregate`, `name_search`; `model_info` with methods on 19+
- [x] Hardening: key lookup by prefix, read-only key scope, model blocklist for read keys, Origin check, client reuse, log redaction
- [x] Tests: unit and live integration

### Phase C (optional, not started)
- [ ] Proxy Odoo's own MCP (`ai_mcp`) tools as `odoo_native_*`, e.g. the `accounting_report_*` tools
- [ ] Per-key Odoo identity (each MCP key carries its own Odoo login and API key)
- [ ] OAuth 2.1 for claude.ai custom connectors
- [ ] `read_binary` tool returning MCP `image` content (≤ 1 MB)

---

## Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-05-29 | Created this agenda | Single reference point for all development planning |
| 2026-10-15 | v3: JSON-2 for Odoo ≥ 19, XML-RPC for ≤ 18 | XML-RPC is deprecated in 19 and removed in Odoo 22 / Online 21.1 |
| 2026-10-15 | `auto` keeps password connections on XML-RPC even on 19+ | JSON-2 accepts only API keys; switching would break existing connections |
| 2026-10-15 | Argument validation failures are `isError` results, not JSON-RPC `-32602` | MCP 2025-11-25 treats input validation as a tool execution error so the model can correct itself; unknown tools and read-only-key writes stay `-32602` |
| 2026-10-15 | `model_info` hides methods introduced by `core` and `base` unless `include_core_methods` | `base` adds ~40 generic `web_*` / gantt / cohort helpers to every model |
| 2026-10-15 | XML-RPC `create` sends `vals_list` positionally | Odoo's `call_kw` reads `args[0]` for create and raises IndexError otherwise |
| 2026-10-15 | Drop the `mcp` package, hand-written protocol layer | Only its types were used; plain dicts keep the schema under our control |

---

## Open Items

- [ ] License mismatch: `LICENSE` is GNU GPL v3, while `pyproject.toml`, the README and the badge say MIT. Pick one and align the files.
- [ ] Upgrade the Alghomlas instance (its Odoo version decides the transport).

---

## History

**v0.2 (May 2026).** A single `mcp_server_odoo/` package with two entry points: a stdio MCP server (`server.py`, 6 tools) and a FastAPI HTTP/SSE server (`http_server.py`, 11 tools including `server_status` and `cache_stats`). It was configured entirely by environment variables (`ODOO_URL`, `ODOO_API_KEY`, `MCP_API_KEY`, cache settings…) and had an in-memory TTL cache and no tests.

**v2.0 (October 2026).** stdio was dropped. The project became one container with the MCP service and a React admin UI; connections, keys and admins moved to SQLite with Fernet-encrypted credentials. It had 10 tools over XML-RPC only.
