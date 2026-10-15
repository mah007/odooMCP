# Changelog

## 3.0.0 — 2026-10-15

### Breaking changes

- **Smaller defaults.** `search_records` returns only `display_name` (and `id`) unless `fields` is passed, and at most 50 records unless `limit` is passed (maximum 500, `MCP_MAX_LIMIT`). `get_record` without `fields` leaves out binary/image fields, one2many lists and chatter/activity fields.
- **Paginated search shape.** `search_records` returns `{records, total, offset, limit, next_offset}` instead of a bare list.
- **Tool errors are results.** A failing tool returns a result with `isError: true` and a text of the form `<ErrorName>: <message>\nHint: <hint>` instead of a JSON-RPC error `-32000`. Unknown tools and write tools called with a read-only key still return a JSON-RPC error (`-32602`).
- **Write and method results.** `create_record` returns `{ids, warnings}` (plus `id` when one record was created); `update_record` and `delete_record` return `{ids, success}`; `execute_method` wraps its value as `{result}`.
- **Metadata as tables.** `get_model_fields` and `list_models` return compact pipe-separated tables instead of `fields_get` / `ir.model` JSON. `model_info` returns purpose, counts, key fields and methods instead of the raw `ir.model` row.
- **Compact JSON.** Responses are unindented, and non-ASCII text (e.g. Arabic) is sent as UTF-8 instead of `\uXXXX` escapes.
- **CORS.** `/mcp` no longer allows every origin. Requests carrying an `Origin` header are refused unless the origin is listed in `MCP_ALLOWED_ORIGINS`.

### Added

- **Dual transport.** XML-RPC for Odoo 10–18 and the JSON-2 API (`/json/2/<model>/<method>`) for Odoo 19+, chosen automatically from the detected version or forced per connection (`api_mode`: `auto`, `xmlrpc`, `json2`). On Odoo 19+, connections that store a password stay on XML-RPC in `auto` mode.
- **New tools.**
  - `get_context`: version, transport, user, time zone, companies and branches, installed apps.
  - `name_search`: resolve a name to record ids.
  - `aggregate`: grouped totals, using `formatted_read_group` on 19+ and `read_group(lazy=False)` on 18 and older, with one normalised output.
- **`model_info` methods.** On Odoo 19+, `model_info` lists the model's public methods by module, with signatures and first doc lines (from `/doc-bearer/<model>.json`, ETag-cached).
- **`company_ids` and `context` on every tool.** `company_ids` is checked against the user's companies; the first id is the active company. Each connection can also have a `default_context`.
- **Output shaping.**
  - Binaries are summarised in all three Odoo formats: base64, `bin_size` strings, and the Odoo 20 `{content, size, filename}` dict.
  - Text and HTML over 2,000 characters are cut, and HTML is converted to text.
  - x2many lists are cut at 50 ids.
  - A 100 KB size guard applies (`MCP_MAX_RESPONSE_BYTES`).
- **Input checks before calling Odoo.** Domains are checked, with string domains parsed. Unknown fields fail with suggestions, and related paths in `fields` are refused. `create_record`/`update_record` warn about readonly computed fields. `create_record` accepts `values_list` (up to 500).
- **`execute_method` arguments.** It takes `ids` and named `kwargs`; legacy positional `args` are still accepted and are mapped to named arguments on JSON-2 (from a table of ORM methods, or from the method signature).
- **MCP protocol compliance.**
  - Protocol version negotiation (2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25) and server `instructions`.
  - `title` and `annotations` on every tool; `outputSchema` and `structuredContent` for clients on 2025-06-18 or later.
  - Notifications and client responses get HTTP 202 with an empty body; `ping` returns `{}`; JSON-RPC batches are supported.
  - `GET /mcp` returns 405, and parse errors return `-32700`.
- **Authentication.** `Authorization: Bearer <key>` is accepted as well as `X-API-Key`.
- **API key scopes.** "Read only" keys do not see the write tools, and the models in `MCP_READ_KEY_BLOCKLIST` are refused for them.
- **Admin UI.**
  - Connection form: API mode, verify SSL, timeout and default context.
  - Connection cards: detected version, transport and the steps of the last test.
  - API key scope can be chosen and edited.
  - Dashboard: average response size and duration per tool; size and transport per request.
- **Tests.** Unit tests (no Odoo needed) and live integration tests in `tests/`.

### Changed

- **Client reuse.** One Odoo client per connection is cached and reused (uid, `fields_get` and context caches). The cache is rebuilt when the connection is edited, tested or activated.
- **API key lookup.** Keys are looked up by their 8-character prefix, so bcrypt verifies one hash instead of every active key, and the result is cached per process.
- **Database migration.** The SQLite database is migrated in place at start-up: new columns are added, existing connections get `api_mode='auto'` and keep `verify_ssl` off as in v2, and existing keys get the `write` scope.
- **Request log.** Each tool call now records the response size and the transport used. Argument values whose key looks like a credential are redacted in debug logs.
- **XML-RPC.** One `ServerProxy` per thread, a timeout, and Odoo exception class names in errors. `create` sends `vals_list` positionally, because Odoo's XML-RPC `call_kw` needs it there; Odoo 10–11 create one record per call.

### Removed

- The `mcp==1.0.0` dependency. Tool definitions are plain dicts, and `httpx` is the only new runtime dependency.
