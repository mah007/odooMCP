# Odoo MCP Server - Enhanced for n8n/ChatGPT/Gemini

## What Was Fixed

This is an enhanced version of the vzeman/odoo-mcp-server with critical fixes and improvements for production use with n8n AI Agents, ChatGPT, and Gemini.

### Critical Fixes Applied

1. **JSON Schema Validation Errors (FIXED)**
   - ✅ Added missing `"items": {}` to `execute_method.args` property
   - ✅ Added proper nested `"items"` structure to `search_records.domain` property
   - ✅ Added proper nested `"items"` structure to `search_count.domain` property
   - **Impact:** Resolves the "Invalid schema for function 'execute_method': In context=('properties', 'args'), array schema missing items" error in n8n

2. **Missing Service Methods (FIXED)**
   - ✅ Added `search_count()` method to `OdooService`
   - ✅ Added `list_models()` method to `OdooService`
   - ✅ Added `get_model_info()` method to `OdooService`
   - **Impact:** All tools defined in `http_server.py` now have corresponding service methods

3. **Security Enhancement (NEW)**
   - ✅ Added API Key authentication middleware
   - ✅ Added `MCP_API_KEY` configuration option
   - ✅ Protects all endpoints except `/health` and root GET
   - **Impact:** Prevents unauthorized access to your Odoo data

### Files Modified

| File | Changes |
| :--- | :--- |
| `mcp_server_odoo/http_server.py` | Schema fixes (lines 166-170, 193-201, 237-245), API key middleware (lines 681-701) |
| `mcp_server_odoo/services/odoo_service.py` | Added `search_count`, `list_models`, `get_model_info` methods (lines 301-376) |
| `mcp_server_odoo/config.py` | Added `api_key` field to `ServerConfig` (line 51), environment variable loading (line 121) |

---

## Deployment Instructions

### 1. Prerequisites

- Docker and Docker Compose installed on your server
- Access to your Odoo instance (URL, database name, username, API key or password)

### 2. Upload Files to Your Server

Upload the entire `odoo-mcp-fixed` directory to your server, replacing the existing `odoo-mcp-server` directory.

```bash
# On your server
cd /path/to/your/project
rm -rf odoo-mcp-server
# Upload the odoo-mcp-fixed directory and rename it
mv odoo-mcp-fixed odoo-mcp-server
cd odoo-mcp-server
```

### 3. Configure Environment Variables

Update your `.env` file or `docker-compose.yml` with the following variables:

```bash
# Odoo Connection (Required)
ODOO_URL=your odoo url
ODOO_DB= data base name
ODOO_USERNAME=user name
ODOO_API_KEY=password or ur api key of odoo

# MCP Server Configuration
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_DEBUG=false
MCP_LOG_LEVEL=INFO

# NEW: API Key for MCP Server Security (Highly Recommended)
MCP_API_KEY=your_secret_api_key_here

# Cache Configuration
CACHE_ENABLED=true
CACHE_TTL=300
CACHE_MAX_SIZE=1000
```

**Important:** Generate a strong, random API key for `MCP_API_KEY`. This is the key that n8n will use to authenticate with your MCP server.

### 4. Rebuild and Restart the Docker Container

```bash
cd /path/to/odoo-mcp-server
docker compose down
docker compose up --build -d
```

### 5. Verify the Deployment

```bash
# Check if the container is running
docker ps

# Check the logs for errors
docker logs mcp-server

# Test the health endpoint (no API key required)
curl http://localhost:8000/health

# Test the tools/list endpoint (API key required if MCP_API_KEY is set)
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_api_key_here" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

If the last command returns a JSON response with a list of tools and no schema validation errors, the deployment is successful.

---

## n8n Integration

### 1. Configure the MCP Client Node in n8n

1. Open your n8n workflow
2. Add or edit the **MCP Client** node
3. Configure the connection:
   - **Endpoint URL:** `http://mcp_server:8000` (or your server's URL)
   - **Authentication:** Add a new credential
     - **Type:** Header Auth
     - **Header Name:** `X-API-Key`
     - **Header Value:** `your_secret_api_key_here` (the value you set in `MCP_API_KEY`)

### 2. Connect to the AI Agent

1. In your n8n workflow, connect the **MCP Client** node to the **AI Agent** node's **Tools** input
2. The AI Agent will now be able to use all the Odoo tools provided by the MCP server

### 3. Test the Integration

1. Activate your workflow
2. Send a test message to the AI Agent (e.g., via Telegram or Webhook)
3. Ask a question that requires Odoo data (e.g., "How many sales orders do we have?")
4. The AI Agent should successfully call the MCP server and return the answer

---

## Troubleshooting

### Error: "Invalid schema for function 'execute_method'"

**Cause:** You are running the old, unfixed code.

**Solution:** Ensure you have deployed the files from this `odoo-mcp-fixed` directory and rebuilt the Docker container.

### Error: "401 Unauthorized" in n8n

**Cause:** The API key in n8n does not match the `MCP_API_KEY` in your server's environment.

**Solution:** Verify that the `X-API-Key` header value in n8n matches the `MCP_API_KEY` environment variable on your server.

### Error: "'OdooService' object has no attribute 'search_count'"

**Cause:** You are running the old `odoo_service.py` file.

**Solution:** Ensure you have deployed the corrected `mcp_server_odoo/services/odoo_service.py` file and rebuilt the Docker container.

### n8n Still Shows Schema Validation Error

**Cause:** n8n is caching the old, invalid schema.

**Solution:** 
1. Restart your n8n instance (Docker container or service)
2. Clear your browser cache
3. Re-open the workflow in n8n

---

## Security Best Practices

1. **Always use HTTPS** in production. Set up a reverse proxy (Nginx) with SSL/TLS certificates.
2. **Use a strong, random API key** for `MCP_API_KEY`. Generate it using: `openssl rand -hex 32`
3. **Restrict network access** to your MCP server. Use firewall rules to allow connections only from your n8n instance.
4. **Rotate your API keys** regularly.
5. **Monitor your server logs** for unauthorized access attempts.

---

## Support

If you encounter any issues not covered in this guide, please check:
1. Docker container logs: `docker logs mcp-server`
2. n8n workflow execution logs
3. Your server's firewall and network configuration

---

## Credits

This enhanced version is based on the excellent work by vzeman (https://github.com/vzeman/odoo-mcp-server).

Enhancements applied:
- JSON Schema fixes for n8n/OpenAI compatibility
- Missing service methods implementation
- API Key authentication for production security
- Comprehensive deployment documentation

---

**Version:** 1.0.0-enhanced  
**Last Updated:** November 22, 2025  
**Compatibility:** n8n, ChatGPT, Gemini, Claude (via n8n)
