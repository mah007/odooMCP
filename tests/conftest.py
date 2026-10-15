"""Shared fixtures. The environment is set before any src module creates its engine."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_TMP = tempfile.mkdtemp(prefix="odoo-mcp-tests-")
os.environ.setdefault("DB_PATH", str(Path(_TMP) / "test.db"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

import pytest  # noqa: E402

from src.mcp.odoo_client import ConnectionConfig, OdooClient  # noqa: E402
from src.mcp.transport.base import MethodNotFound  # noqa: E402
from src.mcp.transport.detect import VersionInfo  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

V20 = VersionInfo(major=20, minor=0, raw="20.0", saas=False)
V17 = VersionInfo(major=17, minor=0, raw="17.0", saas=False)

PARTNER_FIELDS = {
    "id": {"type": "integer", "string": "ID", "store": True, "readonly": True},
    "name": {"type": "char", "string": "Name", "store": True, "searchable": True},
    "display_name": {"type": "char", "string": "Display Name", "store": False, "readonly": True},
    "phone": {"type": "char", "string": "Phone", "store": True},
    "comment": {"type": "html", "string": "Notes", "store": True},
    "image_1920": {"type": "binary", "string": "Image", "store": True},
    "category_id": {"type": "many2many", "string": "Tags", "store": True, "relation": "res.partner.category"},
    "child_ids": {"type": "one2many", "string": "Contacts", "store": True, "relation": "res.partner"},
    "message_ids": {"type": "one2many", "string": "Messages", "store": True, "relation": "mail.message"},
    "company_id": {"type": "many2one", "string": "Company", "store": True, "relation": "res.company"},
    "country_code": {"type": "char", "string": "Country Code", "store": False, "readonly": True},
    "active": {"type": "boolean", "string": "Active", "store": True},
    "create_date": {"type": "datetime", "string": "Created on", "store": True},
    "amount_total": {"type": "monetary", "string": "Total", "store": True, "currency_field": "currency_id"},
    "state": {
        "type": "selection", "string": "State", "store": True,
        "selection": [["draft", "Draft"], ["done", "Done"]],
    },
}


class FakeTransport:
    """Records calls and answers them from a handler map {(model, method): fn(ids, kwargs, context)}."""

    def __init__(self, mode: str = "json2", handlers: dict | None = None) -> None:
        self.mode = mode
        self.calls: list[dict] = []
        self.handlers: dict[tuple[str, str], Any] = handlers or {}

    def call(self, model, method, *, ids=None, kwargs=None, context=None):
        self.calls.append({"model": model, "method": method, "ids": ids, "kwargs": kwargs or {}, "context": context})
        handler = self.handlers.get((model, method))
        if handler is None:
            raise MethodNotFound("werkzeug.exceptions.NotFound", f"no fake for {model}.{method}", 404)
        return handler(ids, kwargs or {}, context or {})

    def call_positional(self, model, method, args, kwargs=None):
        self.calls.append({"model": model, "method": method, "args": args, "kwargs": kwargs or {}})
        return self.handlers[(model, method)](args, kwargs or {}, {})

    def uid(self) -> int:
        return 2

    def close(self) -> None:
        pass


def default_handlers() -> dict:
    users = {
        "id": 2, "name": "Administrator", "login": "admin", "lang": "en_US", "tz": "Asia/Riyadh",
        "company_id": [1, "G+ Partners"], "company_ids": [110, 111, 108, 109, 107, 1],
    }
    return {
        ("res.users", "read"): lambda ids, kw, ctx: [users],
        ("res.partner", "fields_get"): lambda ids, kw, ctx: PARTNER_FIELDS,
    }


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport(handlers=default_handlers())


def make_client(transport: FakeTransport, version: VersionInfo = V20, **cfg: Any) -> OdooClient:
    config = ConnectionConfig(
        url="http://odoo.test", database="db", username="admin", secret="k", **cfg,
    )
    return OdooClient(config, version=version, transport=transport)


@pytest.fixture
def client(fake_transport: FakeTransport) -> OdooClient:
    return make_client(fake_transport)


@pytest.fixture
def doc_sale_order() -> dict:
    return json.loads((FIXTURES / "doc_sale_order.json").read_text())
