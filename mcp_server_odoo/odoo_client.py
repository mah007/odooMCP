"""Odoo XML-RPC client for API communication."""

import xmlrpc.client
import ssl
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
        
        # Create SSL context that doesn't verify certificates (for development)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Initialize XML-RPC endpoints with SSL context
        self.common = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/common"),
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True,
        )
        self.models = xmlrpc.client.ServerProxy(
            urljoin(self.url, "/xmlrpc/2/object"),
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
    ) -> List[int]:
        """Search for record IDs matching the domain."""
        domain = domain or []
        kwargs: Dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        
        return self.execute(model, "search", domain, **kwargs)

    def search_read(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        fields: Optional[List[str]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
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
        
        return self.execute(model, "search_read", domain, **kwargs)

    def read(
        self,
        model: str,
        ids: Union[int, List[int]],
        fields: Optional[List[str]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Read records by IDs."""
        if isinstance(ids, int):
            ids = [ids]
            
        kwargs: Dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
            
        result = self.execute(model, "read", ids, **kwargs)
        return result[0] if len(ids) == 1 else result

    def create(
        self,
        model: str,
        values: Union[Dict[str, Any], List[Dict[str, Any]]],
    ) -> Union[int, List[int]]:
        """Create one or more records."""
        single_record = isinstance(values, dict)
        if single_record:
            values = [values]
        
        result = self.execute(model, "create", values)
        return result[0] if single_record else result

    def write(
        self,
        model: str,
        ids: Union[int, List[int]],
        values: Dict[str, Any],
    ) -> bool:
        """Update records."""
        if isinstance(ids, int):
            ids = [ids]
        
        return self.execute(model, "write", ids, values)

    def unlink(
        self,
        model: str,
        ids: Union[int, List[int]],
    ) -> bool:
        """Delete records."""
        if isinstance(ids, int):
            ids = [ids]
        
        return self.execute(model, "unlink", ids)

    def fields_get(
        self,
        model: str,
        fields: Optional[List[str]] = None,
        attributes: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get field definitions for a model."""
        kwargs: Dict[str, Any] = {}
        if fields is not None:
            kwargs["allfields"] = fields
        if attributes is not None:
            kwargs["attributes"] = attributes
            
        return self.execute(model, "fields_get", **kwargs)

    def get_model_list(self) -> List[Dict[str, Any]]:
        """Get list of all available models."""
        return self.search_read("ir.model", [], ["model", "name", "transient"])
