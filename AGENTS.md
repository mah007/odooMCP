# OdooMCP Project – Agent Guide

This document is meant for Codex CLI or any agent that will run and modify the **OdooMCP** project located at `/home/mahmoud/Projects/odoo-mcp-server`.  It consolidates setup commands, behavioural guidelines and Odoo‑specific considerations.

## Goals of this repository

* Provide a **multi‑channel agent** (MCP) that talks to an Odoo instance via the external API (XML‑RPC).  
* Improve the server’s robustness: if the AI calls a tool with the wrong model, field or domain, do **not** crash.  Instead, return a structured error with hints so the agent can correct itself.
* Support **Odoo 18 and Odoo 19** seamlessly.  Odoo 19’s RPC endpoints are the same `/xmlrpc/2/common` and `/xmlrpc/2/object` used in Odoo 18, but they are deprecated in favour of JSON‑2 and scheduled to be removed in Odoo 20【898064309136105†L2119-L2123】.  Make the endpoint configurable via YAML so a future upgrade can switch easily.
* Provide safe loops for testing and fixing code via Codex.

## Environment and prerequisites

### Tools installed

This guide assumes you have already installed **Codex CLI** on your Ubuntu 24.04/Linux Mint machine.  To verify:

```
codex --version
```

If the CLI asks you to sign in, complete the authentication flow.  When it drops you into a prompt you are ready to work.

### Docker access

The project uses Docker (via `docker compose`).  Ensure Docker is installed and running and that your user is part of the `docker` group:

```bash
docker ps
docker compose version
# If permission denied:
sudo usermod -aG docker \$USER
newgrp docker
```

After adjusting group membership, try `docker ps` again.

### Project location

Clone the project (if you have not already) and change into the repo:

```bash
git clone git@github.com:mah007/odooMCP.git ~/Projects/odoo-mcp-server
cd ~/Projects/odoo-mcp-server
```

Running Codex inside this directory allows it to read and modify files in your working copy.

## How to run and test the server

To start the OdooMCP server locally using Docker:

```bash
docker compose up -d --build
docker compose ps           # show container status
docker compose logs -f --tail=200   # tail logs and watch for errors
```

If the project exposes tests (e.g. via `pytest` or a test script), add a test command here.  Codex will use these commands to check for regressions.

### Recommended Codex workflow

1. **Start Codex** in the repo root:

   ```bash
   cd ~/Projects/odoo-mcp-server
   codex
   ```

2. **Describe the goal** in natural language.  For example:

   > Bring up the environment using `docker compose up -d`, run the test suite, fix any failing tests with minimal changes, and re‑run tests until passing.  Provide the exact commands you executed and summarise any modifications.

3. **Provide approvals** as needed.  Codex asks before running commands or writing files.  Approve `docker compose` commands, Python test runs and Git operations.  Never approve destructive commands like `rm -rf` or `docker system prune` unless you explicitly intend to clean resources.

## Configuration file and Odoo versions

The MCP reads its configuration from a YAML file (for example `config.yml`).  Add an `odoo.version` field so the agent knows which RPC endpoint to use:

```yaml
odoo:
  url: "https://your-odoo-instance"
  db: "your_database"
  username: "admin"
  password: "******"
  version: "18.0"  # or "19.0"
```

### Endpoint selection logic

* For Odoo **19.0 and later**: use the `/xmlrpc/2/common` endpoint for metadata (authentication and version) and `/xmlrpc/2/object` to call model methods via `execute_kw`.  The Odoo 19 docs show authenticating with:

  ```python
  common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
  common.version()  # returns server_version, server_version_info, etc.
  uid = common.authenticate(db, username, password, {})
  ```

  and calling model methods via:

  ```python
  models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
  models.execute_kw(db, uid, password, 'res.partner', 'name_search', ['foo'], {'limit': 10})
  ```

  These examples illustrate the RPC signature【898064309136105†L2119-L2123】【475966977456336†L2310-L2334】.

* For **18.0** (and older): the same `/xmlrpc/2/common` and `/xmlrpc/2/object` endpoints apply.  The 18.0 documentation confirms that `xmlrpc/2/common` is used for meta‑calls such as version and authentication and that `xmlrpc/2/object` calls model methods via `execute_kw`【475966977456336†L2245-L2255】【475966977456336†L2310-L2334】.  Maintaining configurability now allows a future switch to JSON‑2 when the older endpoints are removed.

### Access control

Odoo requires the user to authenticate before most data operations.  Use `common.authenticate(db, username, password, {})` to get a user ID (`uid`).  The returned UID is used on subsequent `execute_kw` calls.  For Odoo Online (hosted at `*.odoo.com`), the user must set a local password to use XML‑RPC【898064309136105†L2149-L2166】.

### Structured error handling

To prevent an AI tool call from halting the process when a wrong parameter is provided:

* Wrap every Odoo call in a `try/except`.  Map specific exceptions to a structured error JSON.  For example:

  ```python
  try:
      records = models.execute_kw(db, uid, password, model, method, args, kwargs)
      return {"ok": True, "data": records}
  except Fault as e:
      return {
          "ok": False,
          "error": {
              "type": "odoo_fault",
              "message": str(e),
              "hint": "Check model, method and fields; use get_model_fields() or search_read() to inspect models",
              "retryable": True
          }
      }
  except Exception as e:
      return {
          "ok": False,
          "error": {
              "type": "unknown",
              "message": str(e),
              "hint": "Unexpected error; verify inputs",
              "retryable": False
          }
      }
  ```

* Inspect exceptions: if the error text contains `Unknown field`, `Unknown model` or `ValueError: Invalid domain`, classify it as `invalid_field`, `invalid_model` or `invalid_domain` respectively and set `retryable` to `true`.  Provide an actionable `hint` telling the agent to fetch available models or fields.

### Pre‑flight validation

Reduce avoidable RPC failures by checking inputs before making RPC calls:

1. **Validate model** – query the `ir.model` model (e.g. via `search_read`) to ensure the requested model exists.  
2. **Validate fields** – call `fields_get` once per model and cache the result for subsequent requests.  If the requested field is not present in the cached list, return an `invalid_field` error without calling Odoo.  
3. **Validate domain** – ensure the domain is a list of conditions (triplets like `[field, operator, value]`).  Reject invalid structures before sending them to Odoo.

### Response schema

All tool responses should use one of these two structures:

* **Success**:

  ```json
  {
    "ok": true,
    "data": <payload>,
    "meta": {
      "odoo_version": "18.0",
      "endpoint_mode": "xmlrpc2",
      "cache": { "fields_get": "hit" }
    }
  }
  ```

* **Error**:

  ```json
  {
    "ok": false,
    "error": {
      "type": "invalid_field | invalid_model | invalid_domain | invalid_method | auth_failed | odoo_fault | transport_error | unknown",
      "message": "<human‑readable explanation>",
      "hint": "<actionable guidance>",
      "retryable": true
    }
  }
  ```

Never throw uncaught exceptions up to the HTTP layer; always return this structured response.

## Git workflow and branching

* Work on branch **`dev`**.  Create it locally if it doesn’t exist: `git checkout -B dev origin/dev || git checkout -b dev`.  
* After making changes, commit with clear messages (`feat:`, `fix:`, `refactor:` etc.) and push to `dev`:

  ```bash
  git add -A
  git commit -m "feat: improve RPC error handling and version selection"
  git push -u origin dev
  ```

* Avoid committing secrets (API keys, passwords, `.env` files).  Use placeholders in example configs.

## Safety rules

* Never run `rm -rf`, `docker system prune`, `docker volume rm`, database drops or mass deletes without an explicit request.  
* Do not install or upgrade packages unless necessary for a fix.  
* Keep fixes minimal; prefer changing code and adding tests over altering dependencies.

## Use of documentation

If you need to reference the external API, consult the official Odoo documentation:

* **Odoo 19.0 External RPC API** – outlines that `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` endpoints are deprecated in Odoo 19 and scheduled for removal in Odoo 20【898064309136105†L2119-L2123】.  It provides example authentication and method calls【898064309136105†L2119-L2123】【475966977456336†L2310-L2334】.
* **Odoo 18.0 External API** – confirms that `xmlrpc/2/common` authenticates and `xmlrpc/2/object` is used with `execute_kw`【475966977456336†L2245-L2255】【475966977456336†L2310-L2334】.

These references can help verify behaviour when implementing new features or debugging.

---

Following this guide will make it easier for Codex to run, test, fix and develop the **OdooMCP** project while respecting the repository’s safety constraints.
