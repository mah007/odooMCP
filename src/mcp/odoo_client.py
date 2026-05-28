"""Odoo XML-RPC client."""

import ssl
import xmlrpc.client
from typing import Any
from urllib.parse import urljoin


def _extract_odoo_error(fault: xmlrpc.client.Fault) -> str:
    """Return just the root-cause line from a verbose Odoo XML-RPC traceback."""
    lines = [l.strip() for l in fault.faultString.splitlines() if l.strip()]
    for line in reversed(lines):
        if ": " in line and not line.startswith("File ") and not line.startswith("Traceback"):
            return line
    return lines[-1] if lines else str(fault)


class OdooClient:
    def __init__(
        self,
        url: str,
        database: str,
        username: str,
        password: str,
        timeout: int = 120,
        verify_ssl: bool = False,
    ) -> None:
        self.url = url.rstrip("/")
        self.database = database
        self.username = username
        self.password = password
        self.uid: int | None = None

        ssl_context = ssl.create_default_context()
        if not verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        opts: dict[str, Any] = {
            "context": ssl_context,
            "allow_none": True,
            "use_builtin_types": True,
        }
        self.common = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/common"), **opts
        )
        self.models = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/object"), **opts
        )

    def authenticate(self) -> int:
        if self.uid is None:
            self.uid = self.common.authenticate(
                self.database, self.username, self.password, {}
            )
            if not self.uid:
                raise ValueError("Odoo authentication failed — check credentials.")
        return self.uid

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        uid = self.authenticate()
        try:
            return self.models.execute_kw(
                self.database, uid, self.password, model, method, args, kwargs
            )
        except xmlrpc.client.Fault as exc:
            raise RuntimeError(_extract_odoo_error(exc)) from None

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict]:
        domain = domain or []
        kwargs: dict[str, Any] = {"offset": offset}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain, **kwargs)

    def search_count(self, model: str, domain: list | None = None) -> int:
        return self.execute(model, "search_count", domain or [])

    def read(self, model: str, ids: list[int], fields: list[str] | None = None) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        return self.execute(model, "read", ids, **kwargs)

    def create(self, model: str, values: dict | list[dict]) -> int | list[int]:
        single = isinstance(values, dict)
        result = self.execute(model, "create", [values] if single else values)
        return result[0] if single else result

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        return self.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute(model, "unlink", ids)

    def fields_get(
        self,
        model: str,
        fields: list[str] | None = None,
        attributes: list[str] | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {}
        if fields is not None:
            kwargs["allfields"] = fields
        if attributes is not None:
            kwargs["attributes"] = attributes
        return self.execute(model, "fields_get", **kwargs)

    def get_model_list(self) -> list[dict]:
        return self.search_read("ir.model", [], ["model", "name", "transient"])

    def get_model_info(self, model: str) -> dict:
        records = self.search_read(
            "ir.model",
            [["model", "=", model]],
            ["model", "name", "field_id", "transient", "info"],
        )
        if not records:
            raise ValueError(f"Model '{model}' not found")
        return records[0]
