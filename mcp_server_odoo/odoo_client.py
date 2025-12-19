"""Odoo XML-RPC client for API communication."""

import ssl
import xmlrpc.client
from typing import Any, Dict, List, Optional, Union

from .config import OdooConfig


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
        endpoints = self.config.get_endpoints()
        self.endpoint_mode = endpoints["endpoint_mode"]
        
        # SSL context: verify certificates by default; allow opt-out via config
        if self.config.verify_ssl:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl._create_unverified_context()
        
        # Initialize XML-RPC endpoints with SSL context
        self.common = xmlrpc.client.ServerProxy(
            endpoints["common"],
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True,
        )
        self.models = xmlrpc.client.ServerProxy(
            endpoints["object"],
            context=ssl_context,
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

    def execute(
        self,
        model: str,
        method: str,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """Execute a method on an Odoo model."""
        uid = self.authenticate()
        return self.models.execute_kw(
            self.database,
            uid,
            self.password,
            model,
            method,
            args,
            kwargs
        )

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
        domain = domain or []
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
        domain = domain or []
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
        if fields is not None:
            kwargs["fields"] = fields
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

    def get_model_list(self, context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get list of all available models."""
        return self.search_read("ir.model", [], ["model", "name", "transient"], context=context)

    def search_count(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count records matching a domain."""
        domain = domain or []
        kwargs: Dict[str, Any] = {}
        if context is not None:
            kwargs["context"] = context
        return self.execute(model, "search_count", domain, **kwargs)

    def name_search(
        self,
        model: str,
        name: str = "",
        domain: Optional[List[List[Any]]] = None,
        operator: str = "ilike",
        limit: Optional[int] = 100,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[List[Any]]:
        """Run a name_search on a model."""
        domain = domain or []
        kwargs: Dict[str, Any] = {"operator": operator}
        if limit is not None:
            kwargs["limit"] = limit
        if context is not None:
            kwargs["context"] = context
        return self.execute(model, "name_search", name, domain, **kwargs)

    def read_group(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        fields: Optional[List[str]] = None,
        groupby: Optional[List[str]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
        lazy: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate records using read_group."""
        domain = domain or []
        fields = fields or []
        groupby = groupby or []
        kwargs: Dict[str, Any] = {"offset": offset, "lazy": lazy}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        if context is not None:
            kwargs["context"] = context
        return self.execute(model, "read_group", domain, fields, groupby, **kwargs)

    def get_version(self) -> Dict[str, Any]:
        """Return Odoo server version info."""
        return self.common.version()

    def render_report_pdf(
        self,
        report_ref: Union[str, int],
        docids: Optional[List[int]] = None,
        data: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Render a PDF report via the public helper on ir.actions.report."""
        docids = docids or []
        kwargs: Dict[str, Any] = {"data": data or {}, "context": context or {}}
        return self.execute("ir.actions.report", "render_report_pdf_rpc", report_ref, docids, **kwargs)
