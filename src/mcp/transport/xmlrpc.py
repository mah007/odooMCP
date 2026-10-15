"""XML-RPC transport (Odoo 18 and older; also usable on 19-21 when forced)."""

import http.client
import re
import socket
import ssl
import threading
import xmlrpc.client
from typing import Any

from src.mcp.transport.base import USER_AGENT, MethodNotFound, OdooError

# Fault codes used by /xmlrpc/2 (odoo/addons/rpc/controllers/xmlrpc.py)
_FAULT_NAMES = {2: "odoo.exceptions.UserError", 3: "odoo.exceptions.AccessDenied", 4: "odoo.exceptions.AccessError"}
# Methods whose parameter names changed across versions but whose positions did not
# (search_count: args → domain in 16, name_search: args → domain in 17, default_get:
# fields_list → fields in 19; create: call_kw reads args[0]). Sent positionally over XML-RPC.
_POSITIONAL: dict[str, tuple[tuple[str, ...], ...]] = {
    "search_count": (("domain", "args"),),
    "name_search": (("name",), ("domain", "args"), ("operator",), ("limit",)),
    "default_get": (("fields", "fields_list"),),
    "create": (("vals_list", "vals"),),
}
_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Denied|Warning|Fault)):\s*(.*)$")


def _extract_odoo_error(fault: xmlrpc.client.Fault) -> str:
    """Return just the root-cause line from a verbose Odoo XML-RPC traceback."""
    lines = [line.strip() for line in str(fault.faultString).splitlines() if line.strip()]
    for line in reversed(lines):
        if ": " in line and not line.startswith("File ") and not line.startswith("Traceback"):
            return line
    return lines[-1] if lines else str(fault)


def fault_to_error(fault: xmlrpc.client.Fault) -> OdooError:
    """Map an XML-RPC fault to an OdooError with the exception class name when it is known."""
    code = fault.faultCode
    if code in _FAULT_NAMES:
        message = str(fault.faultString).strip()
        name = _FAULT_NAMES[code]
        if code == 2 and "does not exist or has been deleted" in message:
            name = "odoo.exceptions.MissingError"
        return OdooError(name, message)
    line = _extract_odoo_error(fault)
    match = _EXC_LINE.match(line)
    if match:
        name, message = match.group(1), match.group(2)
    else:
        name, message = "OdooServerError", line
    if (
        name.endswith("AttributeError")
        or "has no attribute" in message
        or ("method" in message.lower() and "does not exist" in message)
    ):
        return MethodNotFound(name, message)
    return OdooError(name, message)


class _TimeoutTransport(xmlrpc.client.Transport):
    user_agent = USER_AGENT

    def __init__(self, timeout: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._timeout = timeout

    def make_connection(self, host):  # type: ignore[override]
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    user_agent = USER_AGENT

    def __init__(self, timeout: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._timeout = timeout

    def make_connection(self, host):  # type: ignore[override]
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class XmlRpcTransport:
    mode = "xmlrpc"

    def __init__(
        self,
        url: str,
        database: str,
        login: str,
        secret: str,
        *,
        major: int = 18,
        timeout: float = 120,
        verify_ssl: bool = True,
        proxy_factory: Any = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.login = login
        self._secret = secret
        self.major = major
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        # ServerProxy keeps one HTTP connection and is not thread-safe: one per thread.
        self._local = threading.local()
        self._proxy_factory = proxy_factory or self._make_proxy
        self._uid: int | None = None
        self._uid_lock = threading.Lock()

    def _make_proxy(self, endpoint: str) -> xmlrpc.client.ServerProxy:
        if self.url.startswith("https"):
            ctx = ssl.create_default_context()
            if not self.verify_ssl:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            transport: xmlrpc.client.Transport = _TimeoutSafeTransport(
                self.timeout, use_builtin_types=True, context=ctx
            )
        else:
            transport = _TimeoutTransport(self.timeout, use_builtin_types=True)
        return xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/{endpoint}", transport=transport, allow_none=True, use_builtin_types=True
        )

    def _proxy(self, endpoint: str) -> Any:
        proxies = getattr(self._local, "proxies", None)
        if proxies is None:
            proxies = self._local.proxies = {}
        if endpoint not in proxies:
            proxies[endpoint] = self._proxy_factory(endpoint)
        return proxies[endpoint]

    def _invoke(self, endpoint: str, method: str, *args: Any) -> Any:
        try:
            return getattr(self._proxy(endpoint), method)(*args)
        except xmlrpc.client.Fault as exc:
            raise fault_to_error(exc) from None
        except xmlrpc.client.ProtocolError as exc:
            self._local.proxies = {}
            raise OdooError("ProtocolError", f"HTTP {exc.errcode} {exc.errmsg} from {self.url}", exc.errcode) from None
        except (TimeoutError, socket.timeout):
            self._local.proxies = {}
            raise OdooError("Timeout", f"Odoo did not answer within {self.timeout:g} s") from None
        except (OSError, http.client.HTTPException) as exc:
            self._local.proxies = {}
            raise OdooError("ConnectionError", f"Cannot reach {self.url}: {exc}") from None

    def uid(self) -> int:
        if self._uid is None:
            with self._uid_lock:
                if self._uid is None:
                    uid = self._invoke("common", "authenticate", self.database, self.login, self._secret, {})
                    if not uid:
                        raise OdooError(
                            "AuthenticationError",
                            "Odoo rejected the login or credential (XML-RPC authenticate returned no user).",
                            401,
                        )
                    self._uid = int(uid)
        return self._uid

    def call(
        self,
        model: str,
        method: str,
        *,
        ids: list[int] | None = None,
        kwargs: dict | None = None,
        context: dict | None = None,
    ) -> Any:
        kw = dict(kwargs or {})
        if context:
            kw["context"] = {**kw.get("context", {}), **context}
        uid = self.uid()
        if method == "create" and self.major < 12 and "vals_list" in kw:
            # Odoo 10-11: create(vals) takes a single dict
            vals_list = kw.pop("vals_list")
            return [
                self._invoke("object", "execute_kw", self.database, uid, self._secret, model, "create", [vals], kw)
                for vals in vals_list
            ]
        args: list[Any] = [ids] if ids is not None else []
        for names in _POSITIONAL.get(method, ()):
            name = next((n for n in names if n in kw), None)
            if name is None:
                break
            args.append(kw.pop(name))
        return self._invoke("object", "execute_kw", self.database, uid, self._secret, model, method, args, kw)

    def call_positional(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        """v2-style execute_kw with caller-supplied positional args."""
        uid = self.uid()
        return self._invoke(
            "object", "execute_kw", self.database, uid, self._secret, model, method, list(args), dict(kwargs or {})
        )

    def close(self) -> None:
        self._local = threading.local()
