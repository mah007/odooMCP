"""Transport interface shared by the XML-RPC and JSON-2 implementations."""

from typing import Any, Protocol

USER_AGENT = "odoo-mcp-server/3.0.0"


class OdooError(Exception):
    """An error raised by Odoo or while talking to it.

    ``name`` is the Odoo exception class (e.g. ``odoo.exceptions.AccessError``) when known,
    ``status`` the HTTP status for JSON-2 errors.
    """

    def __init__(self, name: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.name = name
        self.message = message
        self.status = status

    @property
    def short_name(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    def __str__(self) -> str:
        return f"{self.short_name}: {self.message}"


class MethodNotFound(OdooError):
    """The model or method does not exist on this Odoo version (used for fallbacks)."""


class Transport(Protocol):
    mode: str

    def call(
        self,
        model: str,
        method: str,
        *,
        ids: list[int] | None = None,
        kwargs: dict | None = None,
        context: dict | None = None,
    ) -> Any: ...

    def uid(self) -> int: ...

    def close(self) -> None: ...
