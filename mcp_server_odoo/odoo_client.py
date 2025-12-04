"""Odoo XML-RPC client for API communication."""

import json
import ssl
import xmlrpc.client
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

from pydantic import BaseModel, Field, ValidationError


class OdooConfig(BaseModel):
    """Configuration for Odoo connection."""

    url: str = Field(..., description="Odoo instance URL")
    database: str = Field(..., description="Odoo database name")
    username: str = Field(..., description="Odoo username (e.g. email)")
    password: Optional[str] = Field(None, description="Odoo password")
    api_key: Optional[str] = Field(None, description="Odoo API key")
    timeout: int = Field(120, description="Request timeout in seconds")
    verify_ssl: bool = Field(
        True, description="Whether to verify SSL certificates (disable for dev only)"
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate that either password or api_key is provided."""
        if not self.password and not self.api_key:
            raise ValueError("Either password or api_key must be provided")


class OdooClient:
    """Client for interacting with Odoo via XML-RPC."""

    def __init__(self, config: OdooConfig) -> None:
        """Initialize Odoo client with configuration."""
        self.config = config
        self.url = config.url.rstrip("/")
        self.database = config.database
        self.username = config.username
        self.password = config.api_key or config.password
        self.uid: Optional[int] = None
        
        if config.verify_ssl:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl._create_unverified_context()

        self.transport = _TimeoutSafeTransport(timeout=config.timeout, context=ssl_context)
        
        # Initialize XML-RPC endpoints with SSL context
        self.common = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/common"),
            transport=self.transport,
            allow_none=True,
            use_builtin_types=True,
        )
        self.models = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/object"),
            transport=self.transport,
            allow_none=True,
            use_builtin_types=True,
        )
        self.db = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/db"),
            transport=self.transport,
            allow_none=True,
            use_builtin_types=True,
        )
        self.report = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/report"),
            transport=self.transport,
            allow_none=True,
            use_builtin_types=True,
        )

    def authenticate(self) -> int:
        """Authenticate with Odoo and return user ID."""
        if self.uid is None:
            self.uid = self.common.authenticate(
                self.database,
                self.username,
                self.password,
                {}
            )
            if not self.uid:
                raise ValueError("Authentication failed. Check your credentials.")
        return self.uid

    @staticmethod
    def _normalize_domain(domain: Optional[Any]) -> List[List[Any]]:
        """Ensure domains accept JSON strings or lists."""
        if domain is None:
            return []

        if isinstance(domain, str):
            try:
                domain = json.loads(domain)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(
                    "Domain must be a list of predicates or a JSON-encoded list"
                ) from exc

        if not isinstance(domain, list):
            raise ValueError("Domain must be a list of predicates")

        return domain

    @staticmethod
    def _normalize_fields(fields: Optional[Any]) -> Optional[List[str]]:
        """Accept comma-separated or JSON-encoded field lists."""
        if fields is None:
            return None

        if isinstance(fields, str):
            fields_str = fields.strip()
            if fields_str.startswith("["):
                try:
                    fields = json.loads(fields_str)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ValueError(
                        "Fields must be a list of strings or JSON-encoded list"
                    ) from exc
            else:
                fields = [item.strip() for item in fields_str.split(",") if item.strip()]

        if not isinstance(fields, list):
            raise ValueError("Fields must be a list of strings")

        if not all(isinstance(field_name, str) for field_name in fields):
            raise ValueError("Each field name must be a string")

        return fields

    def execute(
        self,
        model: str,
        method: str,
        *args: Any,
        context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a method on an Odoo model."""
        uid = self.authenticate()
        if context is not None:
            kwargs.setdefault("context", context)

        return self.models.execute_kw(
            self.database,
            uid,
            self.password,
            model,
            method,
            args,
            kwargs,
        )

    def execute_kw(
        self,
        model: str,
        method: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Direct passthrough to ``execute_kw`` for arbitrary model methods."""
        args = args or []
        kwargs = kwargs or {}
        return self.execute(model, method, *args, context=context, **kwargs)

    def search(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        """Search for record IDs matching the domain."""
        domain = self._normalize_domain(domain)
        kwargs: Dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order

        if context is not None:
            kwargs["context"] = context

        return self.execute(model, "search", domain, **kwargs)

    def search_read(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        fields: Optional[List[str]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search and read records in a single call."""
        domain = self._normalize_domain(domain)
        fields = self._normalize_fields(fields)
        kwargs: Dict[str, Any] = {"offset": offset}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order

        if context is not None:
            kwargs["context"] = context

        return self.execute(model, "search_read", domain, **kwargs)

    def read(
        self,
        model: str,
        ids: Union[int, List[int]],
        fields: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Read records by IDs."""
        if isinstance(ids, int):
            ids = [ids]

        kwargs: Dict[str, Any] = {}
        normalized_fields = self._normalize_fields(fields)
        if normalized_fields is not None:
            kwargs["fields"] = normalized_fields
        if context is not None:
            kwargs["context"] = context

        result = self.execute(model, "read", ids, **kwargs)
        return result[0] if len(ids) == 1 else result

    def create(
        self,
        model: str,
        values: Union[Dict[str, Any], List[Dict[str, Any]]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Union[int, List[int]]:
        """Create one or more records."""
        single_record = isinstance(values, dict)
        if single_record:
            values = [values]

        kwargs: Dict[str, Any] = {}
        if context is not None:
            kwargs["context"] = context

        result = self.execute(model, "create", values, **kwargs)
        return result[0] if single_record else result

    def write(
        self,
        model: str,
        ids: Union[int, List[int]],
        values: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update records."""
        if isinstance(ids, int):
            ids = [ids]

        kwargs: Dict[str, Any] = {}
        if context is not None:
            kwargs["context"] = context

        return self.execute(model, "write", ids, values, **kwargs)

    def unlink(
        self,
        model: str,
        ids: Union[int, List[int]],
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Delete records."""
        if isinstance(ids, int):
            ids = [ids]

        kwargs: Dict[str, Any] = {}
        if context is not None:
            kwargs["context"] = context

        return self.execute(model, "unlink", ids, **kwargs)

    def fields_get(
        self,
        model: str,
        fields: Optional[List[str]] = None,
        attributes: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get field definitions for a model."""
        kwargs: Dict[str, Any] = {}
        if fields is not None:
            kwargs["allfields"] = fields
        if attributes is not None:
            kwargs["attributes"] = attributes
        if context is not None:
            kwargs["context"] = context

        return self.execute(model, "fields_get", **kwargs)

    def get_model_list(self) -> List[Dict[str, Any]]:
        """Get list of all available models."""
        return self.search_read("ir.model", [], ["model", "name", "transient"])

    def get_version_info(self) -> Dict[str, Any]:
        """Return server version metadata."""
        return self.common.version()

    def get_about_info(self) -> Dict[str, Any]:
        """Return server about information when available."""
        about_method = getattr(self.common, "about", None)
        if about_method is None:
            raise AttributeError("common.about not available on this server version")

        return about_method()

    def list_databases(self) -> List[str]:
        """List databases on the Odoo instance."""
        return self.db.list()

    def render_report(
        self,
        report_name: str,
        docids: Union[int, List[int]],
        context: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Render a report using the report endpoint."""
        uid = self.authenticate()
        docids = [docids] if isinstance(docids, int) else docids
        kwargs: Dict[str, Any] = {}
        if context is not None:
            kwargs["context"] = context
        if data is not None:
            kwargs["data"] = data

        return self.report.render_report(self.database, uid, self.password, report_name, docids, kwargs)


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """SafeTransport that applies a per-connection timeout."""

    def __init__(self, *, timeout: int, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self.timeout = timeout

    def make_connection(self, host: str):  # type: ignore[override]
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection
