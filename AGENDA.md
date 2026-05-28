# Odoo MCP Server — Development Agenda

> This document is the single source of truth for project state and roadmap.
> Keep it updated as development progresses.

---

## Project Identity

| Field | Value |
|-------|-------|
| **Name** | odoo-mcp-server |
| **Version** | 0.2.0 |
| **Author** | Mahmoud Abdel Latif (enhanced from Viktor Zeman's original) |
| **License** | MIT |
| **Python** | 3.10+ |
| **Stack** | FastAPI · Uvicorn · MCP 1.0.0 · Pydantic v2 · Loguru · XML-RPC |

---

## What the Project Does

An MCP (Model Context Protocol) server that acts as a **secure bridge** between Odoo ERP and AI agents (ChatGPT, Gemini, Claude) — typically wired through automation platforms like **n8n**.

```
AI Agent (n8n / Claude / ChatGPT)
        ↓  JSON-RPC 2.0
  Odoo MCP Server  ←── API Key Auth
        ↓  XML-RPC
    Odoo Instance (v10–v18)
```

---

## Current Architecture

### Transport Modes

| Mode | File | Entry | Use Case |
|------|------|-------|----------|
| **stdio** | `server.py` | `__main__.py` | Direct MCP client (Claude Code, local agents) |
| **HTTP / SSE** | `http_server.py` | `uvicorn` | Remote clients, n8n, web AI platforms |

### Module Map

```
mcp_server_odoo/
├── __init__.py
├── __main__.py          — stdio entry point
├── server.py            — stdio MCP server (6 tools)
├── http_server.py       — FastAPI HTTP/SSE MCP server (11 tools)
├── odoo_client.py       — raw XML-RPC client (used by stdio)
├── config.py            — Pydantic config: OdooConfig / ServerConfig / CacheConfig
├── logger.py            — Loguru: console + rotating file (logs/)
└── services/
    ├── odoo_service.py  — high-level Odoo service + cache integration (used by HTTP)
    └── cache_service.py — in-memory TTL cache with LRU eviction
```

### Tools Exposed

| Tool | stdio | HTTP | Description |
|------|:-----:|:----:|-------------|
| `search_records` | ✅ | ✅ | Search any model with domain/fields/limit/order |
| `create_record` | ✅ | ✅ | Create one record |
| `update_record` | ✅ | ✅ | Update records by IDs |
| `delete_record` | ✅ | ✅ | Delete records by IDs |
| `get_record` | ✅ | ✅ | Fetch records by IDs |
| `list_models` | ✅ | ✅ | Discover all Odoo models |
| `get_model_fields` | ✅ | ✅ | Get field definitions for a model |
| `execute_method` | ❌ | ✅ | Call any method on any Odoo model |
| `search_count` | ❌ | ✅ | Count records matching a domain |
| `model_info` | ❌ | ✅ | Comprehensive model metadata |
| `server_status` | ❌ | ✅ | Health, uptime, Odoo connection info |
| `cache_stats` | ❌ | ✅ | Cache stats + clear action |

### Environment Variables

```env
# Required — Odoo connection
ODOO_URL=https://your-instance.odoo.com
ODOO_DB=your-database
ODOO_USERNAME=user@example.com
ODOO_API_KEY=...           # or ODOO_PASSWORD
ODOO_TIMEOUT=120

# Server
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_DEBUG=false
MCP_LOG_LEVEL=INFO
MCP_API_KEY=...            # protects all endpoints except GET / and /health

# Cache
CACHE_ENABLED=true
CACHE_TTL=300              # seconds
CACHE_MAX_SIZE=1000
```

### HTTP Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Root info |
| POST | `/` | Yes | Alias → `/mcp` |
| GET | `/health` | No | Odoo connectivity check |
| POST | `/mcp` | Yes | JSON-RPC 2.0 MCP endpoint |

### Deployment

- **Docker Compose** — `docker-compose.yml` (single `mcp-server` service, port 8000)
- Optional profiles: `redis` (session store), `proxy` (Nginx reverse proxy)
- Health check: `curl http://localhost:8000/health`

---

## Known Issues / Technical Debt

- [ ] **SSL verification disabled** in both XML-RPC clients (`ssl.CERT_NONE`) — acceptable for dev, must be addressed for production
- [ ] **`docker-compose.yml` contains hardcoded test credentials** — must be replaced / gitignored before any public deployment
- [ ] **Cache invalidation is a no-op** — `_invalidate_cache()` in `odoo_service.py` does nothing; stale data after writes until TTL expires
- [ ] **In-memory cache only** — Redis service is defined in docker-compose but not integrated; horizontal scaling will lose cache state
- [ ] **Session storage is a plain dict** (`sessions = {}` in `http_server.py`) — not persistent, not thread-safe under load
- [ ] **`OdooConfig` is duplicated** — defined in both `odoo_client.py` and `config.py`; the one in `odoo_client.py` has no URL validator
- [ ] **stdio server has fewer tools than HTTP server** — `execute_method`, `search_count`, `model_info` missing from `server.py`
- [ ] **No tests** — zero test coverage currently

---

## Development Roadmap

> Fill in your priorities below. Use the status labels: `[ ]` Todo · `[~]` In Progress · `[x]` Done

### Phase 1 — Stabilization
- [ ] ...

### Phase 2 — Features
- [ ] ...

### Phase 3 — Production Hardening
- [ ] ...

---

## Decision Log

> Record significant decisions here so future sessions have context.

| Date | Decision | Reason |
|------|----------|--------|
| 2026-05-29 | Created this agenda | Single reference point for all development planning |

---

## Questions / Open Items

- [ ] ...
