"""JSON-2 transport (Odoo 19 and newer): POST /json/2/<model>/<method> with a bearer API key."""

import threading
from typing import Any

import httpx
from loguru import logger

from src.mcp.transport.base import USER_AGENT, MethodNotFound, OdooError

RPC_SCOPE_HINT = (
    "This Odoo version needs an API key with RPC scope: "
    "Odoo → avatar → Preferences → Account Security → New API Key."
)


def response_to_error(resp: httpx.Response) -> OdooError:
    """Turn a JSON-2 error response into an OdooError. The ``debug`` traceback is only logged."""
    status = resp.status_code
    name, message = "HTTPError", resp.reason_phrase or f"HTTP {status}"
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        name = body.get("name") or name
        message = body.get("message") or message
        if body.get("debug"):
            logger.debug("Odoo JSON-2 traceback ({} {}):\n{}", status, name, body["debug"])
    if status == 401:
        message = f"{message}. {RPC_SCOPE_HINT}"
    if status == 404:
        return MethodNotFound(name, message, status)
    return OdooError(name, message, status)


class Json2Transport:
    mode = "json2"

    def __init__(
        self,
        url: str,
        database: str,
        login: str,
        api_key: str,
        *,
        timeout: float = 120,
        verify_ssl: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.login = login
        self.timeout = timeout
        self._http = http_client or httpx.Client(timeout=timeout, verify=verify_ssl)
        self._headers = {
            "Authorization": f"bearer {api_key}",
            "X-Odoo-Database": database,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._uid: int | None = None
        self._uid_lock = threading.Lock()

    def post(self, path: str, body: dict, extra_headers: dict | None = None) -> httpx.Response:
        headers = {**self._headers, **(extra_headers or {})}
        try:
            return self._http.post(f"{self.url}{path}", json=body, headers=headers)
        except httpx.TimeoutException:
            raise OdooError("Timeout", f"Odoo did not answer within {self.timeout:g} s") from None
        except httpx.HTTPError as exc:
            raise OdooError("ConnectionError", f"Cannot reach {self.url}: {exc}") from None

    def call(
        self,
        model: str,
        method: str,
        *,
        ids: list[int] | None = None,
        kwargs: dict | None = None,
        context: dict | None = None,
    ) -> Any:
        body: dict[str, Any] = dict(kwargs or {})
        if ids is not None:
            body["ids"] = ids
        if context:
            body["context"] = {**body.get("context", {}), **context}
        resp = self.post(f"/json/2/{model}/{method}", body)
        if resp.status_code >= 400:
            raise response_to_error(resp)
        if not resp.content:
            return None
        return resp.json()

    def uid(self) -> int:
        """JSON-2 has no authenticate(): look the connection's login up in res.users."""
        if self._uid is None:
            with self._uid_lock:
                if self._uid is None:
                    rows = self.call(
                        "res.users",
                        "search_read",
                        kwargs={"domain": [["login", "=", self.login]], "fields": ["id"], "limit": 1},
                    )
                    if not rows:
                        raise OdooError(
                            "AuthenticationError",
                            f"The API key works but no user with login '{self.login}' is visible to it. "
                            "Check the connection's username.",
                            401,
                        )
                    self._uid = int(rows[0]["id"])
        return self._uid

    def close(self) -> None:
        self._http.close()
