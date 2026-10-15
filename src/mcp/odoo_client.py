"""Odoo client facade: version detection, transport choice, caches and high-level helpers.

Tool handlers only talk to this class; they never know which transport is in use.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.mcp.transport.base import MethodNotFound, OdooError, Transport
from src.mcp.transport.detect import VersionInfo, detect_version, select_mode
from src.mcp.transport.json2 import Json2Transport, response_to_error
from src.mcp.transport.xmlrpc import XmlRpcTransport

FIELDS_TTL = 600
CONTEXT_TTL = 300
FIELD_ATTRIBUTES = [
    "string", "type", "required", "readonly", "store", "relation", "selection", "help",
    "groupable", "sortable", "searchable", "currency_field", "company_dependent", "translate",
]


@dataclass
class ConnectionConfig:
    url: str
    database: str
    username: str
    secret: str
    credential_type: str = "api_key"
    api_mode: str = "auto"
    verify_ssl: bool = True
    timeout: int = 120
    default_context: dict = field(default_factory=dict)
    id: int | None = None


class OdooClient:
    def __init__(
        self,
        config: ConnectionConfig,
        *,
        version: VersionInfo | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self._version = version
        self._transport = transport
        self.mode_note: str | None = None
        self._lock = threading.Lock()
        self._fields_cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._user_cache: tuple[float, dict] | None = None
        self.context_cache: dict[str, tuple[float, dict]] = {}
        self._doc_cache: dict[str, tuple[str | None, dict]] = {}
        self._doc_http: Json2Transport | None = None
        self._group_method: str | None = None
        self._model_fields_present: dict[tuple[str, str], bool] = {}

    # ── Setup ────────────────────────────────────────────────────────────────

    @property
    def version(self) -> VersionInfo:
        if self._version is None:
            self._version = detect_version(self.config.url, verify_ssl=self.config.verify_ssl)
        return self._version

    @property
    def transport(self) -> Transport:
        if self._transport is None:
            with self._lock:
                if self._transport is None:
                    self._transport = self._build_transport()
        return self._transport

    @property
    def mode(self) -> str:
        return self.transport.mode

    @property
    def known_version(self) -> VersionInfo | None:
        """The detected version, or None when detection has not run yet."""
        return self._version

    @property
    def transport_mode(self) -> str | None:
        """The transport in use, or None when it has not been built yet (never triggers detection)."""
        return self._transport.mode if self._transport is not None else None

    def _build_transport(self) -> Transport:
        cfg = self.config
        mode, note = select_mode(cfg.api_mode, self.version, cfg.credential_type)
        self.mode_note = note
        if mode == "json2":
            return Json2Transport(
                cfg.url, cfg.database, cfg.username, cfg.secret,
                timeout=cfg.timeout, verify_ssl=cfg.verify_ssl,
            )
        return XmlRpcTransport(
            cfg.url, cfg.database, cfg.username, cfg.secret,
            major=self.version.major, timeout=cfg.timeout, verify_ssl=cfg.verify_ssl,
        )

    def uid(self) -> int:
        return self.transport.uid()

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        if self._doc_http is not None:
            self._doc_http.close()

    # ── Context ──────────────────────────────────────────────────────────────

    def build_context(self, context: dict | None = None, company_ids: list[int] | None = None) -> dict:
        """Merge order, last wins: connection default_context → tool context → company_ids."""
        ctx: dict[str, Any] = dict(self.config.default_context or {})
        ctx.update(context or {})
        if company_ids:
            ctx["allowed_company_ids"] = [int(c) for c in company_ids]
        if ctx.get("allowed_company_ids"):
            allowed = self.user_info()["company_ids"]
            bad = [c for c in ctx["allowed_company_ids"] if c not in allowed]
            if bad:
                raise OdooError(
                    "InvalidCompany",
                    f"Company ids {bad} are not among the user's companies. Allowed ids: {allowed} "
                    "(see get_context for names).",
                )
        return ctx

    def user_info(self) -> dict:
        now = time.monotonic()
        if self._user_cache and now - self._user_cache[0] < CONTEXT_TTL:
            return self._user_cache[1]
        rows = self.call(
            "res.users", "read", ids=[self.uid()],
            kwargs={"fields": ["name", "login", "lang", "tz", "company_id", "company_ids"]},
        )
        info = rows[0]
        self._user_cache = (now, info)
        return info

    # ── Core calls ───────────────────────────────────────────────────────────

    def call(
        self,
        model: str,
        method: str,
        *,
        ids: list[int] | None = None,
        kwargs: dict | None = None,
        context: dict | None = None,
    ) -> Any:
        return self.transport.call(model, method, ids=ids, kwargs=kwargs, context=context)

    @staticmethod
    def _read_context(context: dict | None, include_binary: bool) -> dict:
        ctx = dict(context or {})
        if not include_binary:
            ctx.setdefault("bin_size", True)
        return ctx

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        context: dict | None = None,
        include_binary: bool = False,
    ) -> list[dict]:
        kw: dict[str, Any] = {"domain": domain or [], "offset": offset}
        if fields is not None:
            kw["fields"] = fields
        if limit is not None:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.call(model, "search_read", kwargs=kw, context=self._read_context(context, include_binary))

    def search_count(self, model: str, domain: list | None = None, context: dict | None = None) -> int:
        return self.call(model, "search_count", kwargs={"domain": domain or []}, context=context)

    def read(
        self, model: str, ids: list[int], fields: list[str] | None = None,
        context: dict | None = None, include_binary: bool = False,
    ) -> list[dict]:
        kw = {"fields": fields} if fields is not None else {}
        return self.call(model, "read", ids=ids, kwargs=kw, context=self._read_context(context, include_binary))

    def create(self, model: str, vals_list: list[dict], context: dict | None = None) -> list[int]:
        result = self.call(model, "create", kwargs={"vals_list": vals_list}, context=context)
        if isinstance(result, int):
            return [result]
        return list(result)

    def write(self, model: str, ids: list[int], vals: dict, context: dict | None = None) -> bool:
        return self.call(model, "write", ids=ids, kwargs={"vals": vals}, context=context)

    def unlink(self, model: str, ids: list[int], context: dict | None = None) -> bool:
        return self.call(model, "unlink", ids=ids, context=context)

    def name_search(
        self, model: str, name: str, domain: list | None = None, operator: str = "ilike",
        limit: int = 10, context: dict | None = None,
    ) -> list[list]:
        return self.call(
            model, "name_search",
            kwargs={"name": name, "domain": domain or [], "operator": operator, "limit": limit},
            context=context,
        )

    def default_get(self, model: str, fields: list[str], context: dict | None = None) -> dict:
        # The parameter is `fields_list` up to Odoo 18 and `fields` in 19+.
        names = ["fields", "fields_list"] if self.version.major >= 19 else ["fields_list", "fields"]
        try:
            return self.call(model, "default_get", kwargs={names[0]: fields}, context=context)
        except OdooError as exc:
            if exc.status != 422 and "unexpected keyword" not in exc.message:
                raise
            return self.call(model, "default_get", kwargs={names[1]: fields}, context=context)

    def fields_get(self, model: str, context: dict | None = None) -> dict[str, dict]:
        """fields_get with the attributes the tools need, cached per model and language."""
        lang = (context or {}).get("lang") or (self.config.default_context or {}).get("lang") or ""
        key = (model, lang)
        now = time.monotonic()
        cached = self._fields_cache.get(key)
        if cached and now - cached[0] < FIELDS_TTL:
            return cached[1]
        ctx = {"lang": lang} if lang else None
        data = self.call(model, "fields_get", kwargs={"attributes": FIELD_ATTRIBUTES}, context=ctx)
        self._fields_cache[key] = (now, data)
        return data

    def has_field(self, model: str, name: str) -> bool:
        key = (model, name)
        if key not in self._model_fields_present:
            self._model_fields_present[key] = name in self.fields_get(model)
        return self._model_fields_present[key]

    # ── Grouping ─────────────────────────────────────────────────────────────

    def group(
        self,
        model: str,
        domain: list,
        groupby: list[str],
        aggregates: list[str],
        *,
        having: list | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        """Raw group rows from formatted_read_group (19+) or read_group(lazy=False) (<= 18)."""
        method = self._group_method or ("formatted_read_group" if self.version.major >= 19 else "read_group")
        try:
            rows = self._group_call(method, model, domain, groupby, aggregates, having, offset, limit, order, context)
        except MethodNotFound:
            other = "read_group" if method == "formatted_read_group" else "formatted_read_group"
            rows = self._group_call(other, model, domain, groupby, aggregates, having, offset, limit, order, context)
            method = other
        self._group_method = method
        return rows

    def _group_call(self, method, model, domain, groupby, aggregates, having, offset, limit, order, context):
        if method == "formatted_read_group":
            kw: dict[str, Any] = {
                "domain": domain, "groupby": groupby, "aggregates": aggregates,
                "having": having or [], "offset": offset, "limit": limit, "order": order or None,
            }
            return self.call(model, method, kwargs=kw, context=context)
        if having:
            raise OdooError(
                "UnsupportedArgument",
                f"`having` needs Odoo 19 or newer (this server runs {self.version.raw}). "
                "Filter the groups yourself instead.",
            )
        agg_fields = [a for a in aggregates if a != "__count"]
        if not agg_fields:
            # Odoo <= 16 aggregates every stored numeric field when `fields` is empty
            agg_fields = [g.split(":")[0] for g in groupby]
        kw = {
            "domain": domain, "fields": agg_fields, "groupby": groupby, "offset": offset,
            "limit": limit, "orderby": order or False, "lazy": False,
        }
        return self.call(model, "read_group", kwargs=kw, context=context)

    # ── API documentation (Odoo 19+) ─────────────────────────────────────────

    def doc_available(self) -> str | None:
        """Return None when /doc-bearer can be used, else the reason it cannot."""
        if self.version.major < 19:
            return f"not available on Odoo {self.version.raw} (needs Odoo 19+)"
        if self.config.credential_type != "api_key":
            return "not available: the connection uses a password; the method listing needs an API key with RPC scope"
        return None

    def doc_model(self, model: str) -> dict:
        """Fetch /doc-bearer/<model>.json (fields and methods with signatures), ETag-cached."""
        reason = self.doc_available()
        if reason:
            raise OdooError("DocUnavailable", reason)
        if isinstance(self.transport, Json2Transport):
            http = self.transport
        else:
            if self._doc_http is None:
                cfg = self.config
                self._doc_http = Json2Transport(
                    cfg.url, cfg.database, cfg.username, cfg.secret,
                    timeout=cfg.timeout, verify_ssl=cfg.verify_ssl,
                )
            http = self._doc_http
        cached = self._doc_cache.get(model)
        headers = {"If-None-Match": cached[0]} if cached and cached[0] else None
        resp: httpx.Response = http.post(f"/doc-bearer/{model}.json", {}, headers)
        if resp.status_code == 304 and cached:
            return cached[1]
        if resp.status_code >= 400:
            raise response_to_error(resp)
        data = resp.json()
        self._doc_cache[model] = (resp.headers.get("ETag"), data)
        return data
