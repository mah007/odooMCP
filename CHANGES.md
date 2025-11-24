# Changelog - Enhanced Odoo MCP Server

## Version 1.0.0-enhanced (November 22, 2025)

### Critical Fixes

#### 1. JSON Schema Validation Errors (n8n Compatibility)

**Problem:** n8n AI Agent was rejecting the MCP server's tool definitions with the error:
```
Bad request - please check your parameters
Invalid schema for function 'execute_method': In context=('properties', 'args'), array schema missing items.
```

**Root Cause:** The OpenAI/n8n tool calling standard requires that all properties with `"type": "array"` must also define an `"items"` property to specify the type of array elements.

**Fix Applied:**

| File | Line | Change |
| :--- | :--- | :--- |
| `http_server.py` | 166-170 | Added `"items": {}` to `execute_method.args` |
| `http_server.py` | 193-201 | Added nested `"items": {"type": "array", "items": {}}` to `search_records.domain` |
| `http_server.py` | 237-245 | Added nested `"items": {"type": "array", "items": {}}` to `search_count.domain` |

**Impact:** The MCP server now passes n8n's schema validation and can be used with AI Agents.

---

#### 2. Missing Service Methods

**Problem:** When tools were called, the server returned:
```
AttributeError: 'OdooService' object has no attribute 'search_count'
```

**Root Cause:** The `http_server.py` defined tools that called methods (`search_count`, `list_models`, `get_model_info`) that did not exist in the `OdooService` class.

**Fix Applied:**

| File | Lines | Method Added |
| :--- | :--- | :--- |
| `odoo_service.py` | 301-324 | `search_count(model, domain)` |
| `odoo_service.py` | 326-347 | `list_models(transient, search)` |
| `odoo_service.py` | 349-376 | `get_model_info(model)` |

**Impact:** All tools defined in the MCP server are now fully functional.

---

### Security Enhancements

#### 3. API Key Authentication

**Problem:** The original MCP server had no authentication mechanism, allowing anyone with network access to query your Odoo data.

**Solution:** Implemented API Key authentication middleware.

**Changes:**

| File | Lines | Change |
| :--- | :--- | :--- |
| `config.py` | 51 | Added `api_key: Optional[str]` field to `ServerConfig` |
| `config.py` | 121 | Added `api_key=os.environ.get("MCP_API_KEY")` to environment loading |
| `http_server.py` | 681-701 | Added API Key authentication middleware |

**How It Works:**
- If `MCP_API_KEY` environment variable is set, all requests (except `/health` and root GET) must include an `X-API-Key` header with the correct key.
- Unauthorized requests receive a `401 Unauthorized` response.
- Health check and root GET endpoints remain publicly accessible for monitoring.

**Impact:** Your Odoo data is now protected from unauthorized access.

---

### Configuration Changes

#### New Environment Variable

| Variable | Required | Default | Description |
| :--- | :--- | :--- | :--- |
| `MCP_API_KEY` | Optional | `None` | API key for server authentication. If set, all requests must include this key in the `X-API-Key` header. |

**Recommendation:** Always set `MCP_API_KEY` in production environments. Generate a strong key using:
```bash
openssl rand -hex 32
```

---

### Deployment Changes

#### New Files

| File | Purpose |
| :--- | :--- |
| `DEPLOYMENT_GUIDE.md` | Comprehensive deployment and integration guide |
| `deploy.sh` | Automated deployment script |
| `CHANGES.md` | This changelog |

---

### Compatibility

This enhanced version is **fully backward compatible** with the original vzeman/odoo-mcp-server, with the following additions:

- **New optional environment variable:** `MCP_API_KEY` (if not set, the server behaves exactly as before, with no authentication)
- **New service methods:** `search_count`, `list_models`, `get_model_info` (these were missing in the original)
- **Fixed JSON schemas:** The tool definitions now conform to the OpenAI/n8n standard

**Migration Path:** Simply replace your existing code with this enhanced version and rebuild your Docker container. No breaking changes.

---

### Testing

All fixes have been validated against:
- ✅ n8n AI Agent (MCP Client node)
- ✅ OpenAI tool calling schema validation
- ✅ Odoo 18.0 (via XML-RPC)

---

### Credits

Original repository: https://github.com/vzeman/odoo-mcp-server  
Enhanced by: Mahmoud Abdel Latif  
Date: November 22, 2025
