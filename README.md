# Odoo MCP Server v2

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-required-blue)](https://www.docker.com/)
[![Odoo](https://img.shields.io/badge/Odoo-16.0%20%E2%80%93%2018.0-blueviolet)](https://www.odoo.com/)

A production-ready [Model Context Protocol](https://modelcontextprotocol.io/) server for Odoo, with a built-in web admin UI. Lets any MCP-compatible AI agent (Claude, ChatGPT, n8n, etc.) query and manipulate Odoo data securely over JSON-RPC 2.0.

---

## Architecture

One Docker container, two services:

```
┌─────────────────────────────────────────────┐
│                                             │
│  MCP Service          port 9100 (default)   │
│  JSON-RPC 2.0 endpoint at POST /mcp         │
│  · X-API-Key header authentication          │
│  · 10 Odoo tools (search, CRUD, execute…)   │
│  · Logs every request to SQLite             │
│                                             │
│  Controller / Admin UI  port 9101 (default) │
│  React SPA + REST API at /api/*             │
│  · First-run setup wizard                   │
│  · Odoo connection CRUD + live test         │
│  · API key management                       │
│  · Dashboard: request stats + error log     │
│                                             │
│  Shared SQLite DB  data/mcp.db              │
└─────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/mah007/odooMCP.git
cd odooMCP
cp .env.example .env
```

Edit `.env` — only three values needed:

```bash
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-random-32-byte-hex-string

MCP_PORT=9100
CONTROLLER_PORT=9101
```

> Odoo credentials are **not** stored in `.env`. You configure them through the admin UI after first boot.

### 2. Build and start

```bash
docker compose up --build -d
docker compose logs -f
```

### 3. First-run setup

1. Open `http://localhost:9101` → you'll be redirected to `/setup`
2. Create an admin account
3. Log in → go to **Connections** → **Add Connection**
4. Fill in your Odoo URL, database, username, and API key/password → **Test** → **Activate**
5. Go to **API Keys** → **Generate** → copy the key (shown once)

### 4. Call the MCP endpoint

```bash
# List available tools
curl -s -X POST http://localhost:9100/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' | jq .

# Search for customers
curl -s -X POST http://localhost:9100/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{
    "jsonrpc":"2.0","method":"tools/call","id":2,
    "params":{
      "name":"search_records",
      "arguments":{"model":"res.partner","domain":[["customer_rank",">",0]],"fields":["name","email"],"limit":10}
    }
  }' | jq .
```

---

## Available Tools

| Tool | Description |
|------|-------------|
| `search_records` | Search records with an Odoo domain filter |
| `get_record` | Fetch specific records by ID |
| `create_record` | Create a new record |
| `update_record` | Update existing records |
| `delete_record` | Delete records by ID |
| `search_count` | Count records matching a domain |
| `list_models` | List all available Odoo models |
| `get_model_fields` | Get field definitions for a model |
| `model_info` | Get metadata for a model (name, field count, etc.) |
| `execute_method` | Call any method on any model (`read_group`, `name_search`, etc.) |

---

## Connecting an AI Agent

### Claude / Claude Code

Add to your MCP config (`~/.claude/mcp_config.json`):

```json
{
  "mcpServers": {
    "odoo": {
      "url": "http://localhost:9100/mcp",
      "headers": { "X-API-Key": "YOUR_KEY" }
    }
  }
}
```

### n8n

1. Add an **MCP Client** node
2. Set **Endpoint URL** to `http://<server>:9100/mcp`
3. Set **Authentication** → Header Auth → Name: `X-API-Key`, Value: your key

### Direct HTTP (any HTTP client)

All calls are `POST /mcp` with `Content-Type: application/json` and `X-API-Key` header. The body is a standard JSON-RPC 2.0 object:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "<tool_name>",
    "arguments": { ... }
  }
}
```

---

## Admin UI Endpoints

All routes require `Authorization: Bearer <JWT>` except `/api/auth/*`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/setup` | Create first admin (only works once) |
| POST | `/api/auth/login` | Login → JWT (24h) |
| GET/POST | `/api/connections` | List / add Odoo connections |
| PUT/DELETE | `/api/connections/{id}` | Edit / delete a connection |
| POST | `/api/connections/{id}/test` | Live XML-RPC test |
| POST | `/api/connections/{id}/activate` | Set as active connection |
| GET/POST | `/api/api-keys` | List / generate API keys |
| DELETE | `/api/api-keys/{id}` | Revoke an API key |
| GET | `/api/dashboard` | Stats + recent error log |

---

## Security

- API keys are stored as **bcrypt hashes** — the plaintext is shown once at generation and never stored
- Odoo credentials are stored **Fernet-encrypted** using `SECRET_KEY`
- Admin sessions use **JWT** (24h expiry, signed with `SECRET_KEY`)
- `SECRET_KEY` is the only secret that must be kept safe; rotate it by updating `.env` and restarting

---

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run services locally (without Docker)
cp .env.example .env  # edit as needed
uvicorn src.mcp.app:app --port 9100 &
uvicorn src.controller.app:app --port 9101

# Build frontend separately
cd frontend && npm install && npm run build
```

---

## License

MIT — see [LICENSE](LICENSE).

Built by **Mahmoud Abdel Latif**. Based on the original `odoo-mcp-server` by Václav Zeman.
