"""Odoo service for API communication."""

import json
import xmlrpc.client
import ssl
from typing import Any, Dict, List, Optional, Union
from ..config import get_config
from ..logger import get_logger
from .cache_service import CacheService, get_cache_service

logger = get_logger(__name__)


class OdooService:
    """Service for interacting with Odoo via XML-RPC."""

    def __init__(self):
        """Initialize Odoo service with configuration."""
        self.config = get_config().odoo
        self.cache = get_cache_service()
        self.url = self.config.url
        self.database = self.config.database
        self.username = self.config.username
        self.password = self.config.api_key or self.config.password
        self.uid: Optional[int] = None
        
        # Create SSL context that doesn't verify certificates (for development)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Initialize XML-RPC clients with SSL context
        self.common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common",
            context=ssl_context
        )
        self.models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", 
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True
        )
        
        logger.info(f"Odoo service initialized for {self.url}/{self.database}")

    @staticmethod
    def _normalize_domain(domain: Optional[Any]) -> List[List[Any]]:
        """Ensure the domain is a list of lists.

        Accepts JSON-encoded strings for convenience and raises a clear
        ValueError when the structure cannot be coerced.
        """

        if domain is None:
            return []

        if isinstance(domain, str):
            try:
                parsed = json.loads(domain)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(
                    "Domain must be a list of domain predicates or a JSON-encoded list"
                ) from exc
            domain = parsed

        if not isinstance(domain, list):
            raise ValueError("Domain must be a list of domain predicates")

        return domain

    @staticmethod
    def _normalize_fields(fields: Optional[Any]) -> Optional[List[str]]:
        """Ensure fields is a list of strings.

        Handles comma-separated or JSON-encoded strings and provides
        clear feedback when the input cannot be normalized.
        """

        if fields is None:
            return None

        if isinstance(fields, str):
            fields_str = fields.strip()
            # Try JSON-encoded list first
            if fields_str.startswith("["):
                try:
                    parsed = json.loads(fields_str)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ValueError(
                        "Fields must be a list of strings or a JSON-encoded list"
                    ) from exc
                fields = parsed
            else:
                # Treat as comma-separated string
                fields = [item.strip() for item in fields_str.split(",") if item.strip()]

        if not isinstance(fields, list):
            raise ValueError("Fields must be a list of strings")

        if not all(isinstance(field_name, str) for field_name in fields):
            raise ValueError("Each field name must be a string")

        return fields

    def authenticate(self) -> int:
        """Authenticate with Odoo and return user ID."""
        if self.uid is None:
            cache_key = f"auth:{self.username}:{self.database}"
            cached_uid = self.cache.get(cache_key)
            
            if cached_uid:
                self.uid = cached_uid
                logger.debug("Using cached authentication")
            else:
                logger.info("Authenticating with Odoo...")
                self.uid = self.common.authenticate(
                    self.database,
                    self.username,
                    self.password,
                    {}
                )
                if not self.uid:
                    raise ValueError("Authentication failed. Check your credentials.")
                
                # Cache authentication for 1 hour
                self.cache.set(cache_key, self.uid, ttl=3600)
                logger.info(f"Authentication successful, user ID: {self.uid}")
        
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
        
        logger.debug(f"Executing {model}.{method} with args={args}, kwargs={kwargs}")
        
        try:
            result = self.models.execute_kw(
                self.database,
                uid,
                self.password,
                model,
                method,
                args,
                kwargs
            )
            logger.debug(f"Execution successful, result type: {type(result)}")
            return result
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            raise

    def search(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
    ) -> List[int]:
        """Search for record IDs matching the domain."""
        domain = self._normalize_domain(domain)
        kwargs: Dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        
        # Generate cache key
        cache_key = self.cache.generate_key(
            "search", model, str(domain), offset, limit, order
        )
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.execute(model, "search", domain, **kwargs)
        
        # Cache the result
        self.cache.set(cache_key, result)
        
        return result

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
        domain = self._normalize_domain(domain)
        fields = self._normalize_fields(fields)
        kwargs: Dict[str, Any] = {"offset": offset}
        if fields is not None:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        
        # Generate cache key
        cache_key = self.cache.generate_key(
            "search_read", model, str(domain), str(fields), offset, limit, order
        )
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.execute(model, "search_read", domain, **kwargs)
        
        # Cache the result
        self.cache.set(cache_key, result)
        
        return result

    def read(
        self,
        model: str,
        ids: Union[int, List[int]],
        fields: Optional[List[str]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Read records by IDs."""
        if isinstance(ids, int):
            ids = [ids]
            single_record = True
        else:
            single_record = False

        kwargs: Dict[str, Any] = {}
        normalized_fields = self._normalize_fields(fields)
        if normalized_fields is not None:
            kwargs["fields"] = normalized_fields

        # Generate cache key
        cache_key = self.cache.generate_key(
            "read", model, str(sorted(ids)), str(fields)
        )
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result[0] if single_record and cached_result else cached_result
        
        result = self.execute(model, "read", ids, **kwargs)
        
        # Cache the result
        self.cache.set(cache_key, result)
        
        return result[0] if single_record and result else result

    def create(
        self,
        model: str,
        values: Union[Dict[str, Any], List[Dict[str, Any]]],
    ) -> Union[int, List[int]]:
        """Create one or more records."""
        single_record = isinstance(values, dict)
        if single_record:
            values = [values]
        
        logger.info(f"Creating {len(values)} record(s) in {model}")
        result = self.execute(model, "create", values)
        
        # Clear related cache entries
        self._invalidate_cache(model)
        
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
        
        logger.info(f"Updating {len(ids)} record(s) in {model}")
        result = self.execute(model, "write", ids, values)
        
        # Clear related cache entries
        self._invalidate_cache(model)
        
        return result

    def unlink(
        self,
        model: str,
        ids: Union[int, List[int]],
    ) -> bool:
        """Delete records."""
        if isinstance(ids, int):
            ids = [ids]
        
        logger.info(f"Deleting {len(ids)} record(s) from {model}")
        result = self.execute(model, "unlink", ids)
        
        # Clear related cache entries
        self._invalidate_cache(model)
        
        return result

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
        
        # Generate cache key
        cache_key = self.cache.generate_key(
            "fields_get", model, str(fields), str(attributes)
        )
        
        # Try cache first (fields don't change often)
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.execute(model, "fields_get", **kwargs)
        
        # Cache for longer (1 hour) since fields don't change often
        self.cache.set(cache_key, result, ttl=3600)
        
        return result

    def get_model_list(self) -> List[Dict[str, Any]]:
        """Get list of all available models."""
        cache_key = "model_list"
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.search_read("ir.model", [], ["model", "name", "transient"])
        
        # Cache for longer (1 hour) since models don't change often
        self.cache.set(cache_key, result, ttl=3600)
        
        return result

    def search_count(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
    ) -> int:
        """Count records matching the domain."""
        domain = domain or []
        
        # Generate cache key
        cache_key = self.cache.generate_key(
            "search_count", model, str(domain)
        )
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.execute(model, "search_count", domain)
        
        # Cache the result
        self.cache.set(cache_key, result)
        
        return result

    def list_models(
        self,
        transient: bool = False,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get list of available models with optional filtering."""
        models = self.get_model_list()
        
        # Filter out transient models if requested
        if not transient:
            models = [m for m in models if not m.get("transient", False)]
        
        # Filter by search term if provided
        if search:
            search_lower = search.lower()
            models = [
                m for m in models
                if search_lower in m.get("model", "").lower()
                or search_lower in m.get("name", "").lower()
            ]
        
        return models

    def get_model_info(
        self,
        model: str,
    ) -> Dict[str, Any]:
        """Get comprehensive information about a model."""
        # Get model metadata
        models = self.search_read(
            "ir.model",
            [["model", "=", model]],
            ["name", "info", "transient", "modules"]
        )
        
        if not models:
            raise ValueError(f"Model '{model}' not found")
        
        model_info = models[0]
        
        # Get field information
        fields = self.fields_get(model)
        
        return {
            "model": model,
            "name": model_info.get("name"),
            "transient": model_info.get("transient", False),
            "modules": model_info.get("modules", ""),
            "fields": fields,
            "field_count": len(fields),
        }

    def _invalidate_cache(self, model: str) -> None:
        """Invalidate cache entries related to a model."""
        # This is a simple implementation - in production you might want
        # more sophisticated cache invalidation
        logger.debug(f"Invalidating cache for model: {model}")
        # For now, we don't implement selective cache invalidation
        # The cache will naturally expire based on TTL


# Global Odoo service instance
_odoo_service: Optional[OdooService] = None


def get_odoo_service() -> OdooService:
    """Get or create global Odoo service instance."""
    global _odoo_service
    if _odoo_service is None:
        _odoo_service = OdooService()
    return _odoo_service
