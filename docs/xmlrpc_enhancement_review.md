# Odoo XML-RPC Coverage Review and Enhancement List

## Current MCP tool surface
- The MCP server exposes six tools (search, create, update, delete, get record, model metadata) that wrap `search_read`, `create`, `write`, `unlink`, `read`, and `fields_get` via the XML-RPC `object` endpoint. Tool schemas accept minimal arguments (model, domain, ids, fields, pagination) and return raw JSON payloads. 【F:mcp_server_odoo/server.py†L46-L313】
- Backend service code uses `execute_kw` against `/xmlrpc/2/object` and caches results, but it only implements helpers for record CRUD, `fields_get`, `search_count`, and listing models through `ir.model`. There are no helpers for other common or database-level XML-RPC endpoints. 【F:mcp_server_odoo/services/odoo_service.py†L13-L376】
- Project documentation advertises compatibility through Odoo 18.0; support for 19.0 is not yet represented in messaging. 【F:README.md†L8-L99】

## Gaps versus full XML-RPC capabilities (Odoo 10–19)
1. **Common endpoint coverage**
   - Missing `common.version()`, `about()`, and `timezone`/context discovery helpers that are available across versions and useful for feature negotiation.
   - No exposure of the `common.authenticate` result metadata (e.g., access rights) beyond a cached UID.

2. **Database management APIs**
   - No access to `/xmlrpc/2/db` endpoints such as `list`, `create`, `duplicate_database`, `drop`, `backup`, and `restore`, which are required to claim “all XML-RPC commands.”

3. **Reporting and workflow execution**
   - The `report` endpoint (e.g., `render_report`, `report_download`) and legacy workflow calls (`exec_workflow` on older versions) are not exposed.

4. **Object-level method passthrough**
   - There is no generic `execute_kw`/`execute` passthrough tool to call arbitrary model methods (server actions, button clicks, `name_search`, `onchange`, `fields_view_get`, etc.) with full positional and keyword argument control. Current helpers restrict payloads to a handful of CRUD patterns.

5. **Version-specific argument differences**
   - The server does not surface which arguments or method names differ between versions (e.g., `execute` vs `execute_kw`, `report` options changing in v14+, removal of workflow in v13). There is no compatibility matrix or runtime negotiation to validate inputs per Odoo version.

6. **Session/context management**
   - No support for passing `context` dictionaries (language, timezone, permissions) with every call or persisting session tokens/cookies for installations that require them.

7. **Security and throttling hooks**
   - Lacks per-tool authorization, rate limits, or payload size limits to safely expose powerful database and system-level XML-RPC calls.

8. **Schema and discoverability**
   - Tool schemas are hand-written and static; there is no automated schema generation from Odoo metadata (fields, required parameters, selection values) to guide callers about valid arguments per method and version.

9. **Error normalization**
   - Exceptions from XML-RPC are returned as plain text; there is no structured error model that distinguishes authentication failures, access errors, validation issues, or missing methods.

## Enhancement backlog to reach full coverage
- **Expose generic XML-RPC tools**
  - Add a tool that directly proxies `execute_kw` with positional args (`args`) and keyword args (`kwargs`) for any model/method to cover the entire object API surface, plus an escape hatch for legacy `execute` where needed. Provide optional `context` injection.
  - Add tools for `common.version`, `common.about`, and explicit authentication that returns UID and server version to allow agents to adapt to capabilities.
  - Implement database endpoint tools (list, create, duplicate, drop, backup/restore) guarded by configuration flags to avoid unsafe defaults.
  - Provide reporting tools for `/xmlrpc/2/report` (render, download) and a legacy workflow executor for v10–v12 where supported.

- **Version awareness and validation**
  - Detect server version at startup and load a compatibility map describing which methods/endpoints and arguments are available from v10–v19. Use it to validate tool calls and return informative guidance when a method is unavailable in the target version.

- **Context and session handling**
  - Extend client/service helpers to accept an optional `context` dict on every call, including language and timezone. Cache and reuse session tokens or cookies when the server is configured for authenticated sessions.

- **Schema generation and discoverability**
  - Build dynamic tool schemas from Odoo metadata (`fields_get`, `fields_view_get`, `name_search` results) so agents can request permissible field names, selection values, and required parameters per model/action. Offer a “describe method” tool that introspects `ir.model.fields` and view architecture to infer expected arguments.

- **Safety controls**
  - Add per-tool authorization and rate limiting, with configuration to disable high-risk operations (database drop/backup/restore, report rendering) unless explicitly allowed. Enforce maximum payload sizes and execution timeouts when proxying arbitrary methods.

- **Error handling and logging**
  - Normalize XML-RPC errors into structured responses (error type, Odoo message, debug context) to help agents react appropriately. Enrich logs with correlation IDs and request summaries for auditing.

- **Documentation and version matrix**
  - Update README/docs to state v10–v19 coverage, document the new tools and safety controls, and publish a compatibility matrix that lists available endpoints and argument nuances per Odoo version.
