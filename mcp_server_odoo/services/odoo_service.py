"""Odoo service for API communication."""

import base64
import ssl
import time
import xmlrpc.client
from typing import Any, Dict, List, Optional, Union
import httpx

from ..config import OdooConfig, get_config
from ..logger import get_logger
from .cache_service import CacheService, get_cache_service

logger = get_logger(__name__)


class OdooServiceError(Exception):
    """Structured error for Odoo operations."""

    def __init__(self, error_type: str, message: str, hint: str, retryable: bool = True):
        super().__init__(message)
        self.error_type = error_type
        self.hint = hint
        self.retryable = retryable


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
        endpoints = self.config.get_endpoints()
        self.endpoint_mode = endpoints["endpoint_mode"]
        self.common_endpoint = endpoints["common"]
        self.object_endpoint = endpoints["object"]
        self.report_endpoint = endpoints.get("report")
        
        # SSL context: verify certificates by default; allow opt-out via config
        if self.config.verify_ssl:
            ssl_context = ssl.create_default_context()
        else:
            ssl_context = ssl._create_unverified_context()
        
        # Initialize XML-RPC clients with SSL context
        self.common = xmlrpc.client.ServerProxy(
            self.common_endpoint,
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True,
        )
        # Report endpoint (XML-RPC)
        self.report = xmlrpc.client.ServerProxy(
            self.report_endpoint,
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True,
        )
        self.models = xmlrpc.client.ServerProxy(
            self.object_endpoint,
            context=ssl_context,
            allow_none=True,
            use_builtin_types=True
        )
        
        logger.info(
            f"Odoo service initialized for {self.url}/{self.database} "
            f"(version={self.config.version}, endpoint_mode={self.endpoint_mode})"
        )

    def _build_meta(
        self,
        cache_meta: Optional[Dict[str, str]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build metadata describing the Odoo connection and cache usage."""
        meta: Dict[str, Any] = {
            "odoo_version": self.config.version,
            "endpoint_mode": self.endpoint_mode,
        }
        if cache_meta:
            meta["cache"] = cache_meta
        if duration_ms is not None:
            meta["duration_ms"] = duration_ms
        if extra_meta:
            meta.update(extra_meta)
        return meta

    def _classify_exception(self, exc: Exception) -> OdooServiceError:
        """Classify an exception into a structured OdooServiceError."""
        if isinstance(exc, OdooServiceError):
            return exc

        message = str(exc)
        lower_msg = message.lower()
        error_type = "unknown"
        hint = "Unexpected error; verify inputs"
        retryable = False

        if isinstance(exc, xmlrpc.client.Fault):
            error_type = "odoo_fault"
            retryable = True
            hint = "Check model, method and fields; use get_model_fields() or search_read() to inspect models"

            if "unknown field" in lower_msg:
                error_type = "invalid_field"
                hint = "Check model fields via get_model_fields() before calling this method"
            elif "unknown model" in lower_msg:
                error_type = "invalid_model"
                hint = "Use list_models to discover available models"
            elif "invalid domain" in lower_msg or "invalid search domain" in lower_msg:
                error_type = "invalid_domain"
                hint = "Domain must be a list of [field, operator, value] triplets"
            elif "unknown method" in lower_msg or "has no attribute" in lower_msg:
                error_type = "invalid_method"
                hint = "Verify the method name and arguments"

        elif isinstance(exc, xmlrpc.client.ProtocolError):
            error_type = "transport_error"
            retryable = True
            hint = "Check network connectivity and the configured Odoo URL"

        elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            error_type = "transport_error"
            retryable = True
            hint = "Check network connectivity and the configured Odoo URL"

        elif isinstance(exc, ValueError):
            if "authentication failed" in lower_msg:
                error_type = "auth_failed"
                retryable = False
                hint = "Verify Odoo credentials or API key"
            elif "domain" in lower_msg:
                error_type = "invalid_domain"
                retryable = True
            hint = "Domain must be a list of [field, operator, value] triplets"

        return OdooServiceError(error_type, message, hint, retryable)

    def build_success(
        self,
        data: Any,
        cache_meta: Optional[Dict[str, str]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build a structured success response."""
        return {
            "ok": True,
            "data": data,
            "meta": self._build_meta(cache_meta=cache_meta, extra_meta=extra_meta, duration_ms=duration_ms),
        }

    def build_error(self, exc: Exception, duration_ms: Optional[float] = None) -> Dict[str, Any]:
        """Build a structured error response."""
        error = self._classify_exception(exc)
        return {
            "ok": False,
            "error": {
                "type": error.error_type,
                "message": str(error),
                "hint": error.hint,
                "retryable": error.retryable,
            },
            "meta": self._build_meta(duration_ms=duration_ms),
        }

    def _validate_domain(self, domain: Optional[List[List[Any]]]) -> List[List[Any]]:
        """Validate domain structure before executing."""
        if domain is None:
            return []
        if not isinstance(domain, list):
            raise OdooServiceError(
                "invalid_domain",
                "Domain must be a list",
                "Provide domain as a list of [field, operator, value] triplets",
                True,
            )

        normalized: List[List[Any]] = []
        for clause in domain:
            if not isinstance(clause, (list, tuple)) or len(clause) != 3:
                raise OdooServiceError(
                    "invalid_domain",
                    "Domain clauses must have exactly three items",
                    "Use domain entries like ['name', 'ilike', 'John']",
                    True,
                )
            normalized.append(list(clause))

        return normalized

    def _validate_model(self, model: str) -> str:
        """Ensure the model exists before making calls."""
        if model == "ir.model":
            return "skip"
        models, cache_status = self.get_model_list(return_cache_status=True)
        if not any(m.get("model") == model for m in models):
            raise OdooServiceError(
                "invalid_model",
                f"Unknown model '{model}'",
                "Use list_models to discover available models before calling tools",
                True,
            )
        return cache_status

    def _validate_fields(self, model: str, fields: List[str]) -> str:
        """Validate fields against cached metadata when available."""
        if not fields:
            return "skip"

        def _normalize(field_name: str) -> str:
            """Strip aggregation suffixes like ':sum' used in read_group."""
            if isinstance(field_name, str) and ":" in field_name:
                return field_name.split(":", 1)[0]
            return field_name

        field_info, cache_status = self.fields_get(model, return_cache_status=True)
        invalid_fields = [field for field in fields if _normalize(field) not in field_info]
        if invalid_fields:
            raise OdooServiceError(
                "invalid_field",
                f"Unknown field(s) for model '{model}': {', '.join(invalid_fields)}",
                "Use get_model_fields to inspect available fields before retrying",
                True,
            )
        return cache_status
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
                try:
                    self.uid = self.common.authenticate(
                        self.database,
                        self.username,
                        self.password,
                        {}
                    )
                except Exception as exc:
                    raise self._classify_exception(exc)

                if not self.uid:
                    raise OdooServiceError(
                        "auth_failed",
                        "Authentication failed. Check your credentials.",
                        "Verify Odoo username/password or API key, and ensure the database is correct",
                        False,
                    )
                
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
        except Exception as exc:
            logger.error(f"Execution failed: {exc}")
            raise self._classify_exception(exc)

    def _execute_with_retry(self, func, attempts: int = 3, backoff_base: float = 0.2) -> Any:
        """Execute a callable with simple retry/backoff for retryable transport faults."""
        for attempt in range(attempts):
            try:
                return func()
            except Exception as exc:
                error = self._classify_exception(exc)
                is_last = attempt >= attempts - 1
                if not error.retryable or is_last:
                    raise error
                sleep_for = backoff_base * (2 ** attempt)
                logger.warning(
                    f"Retryable error ({error.error_type}): {error}. "
                    f"Retrying in {sleep_for:.2f}s (attempt {attempt + 1}/{attempts})"
                )
                time.sleep(sleep_for)

    def search(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order: Optional[str] = None,
    ) -> List[int]:
        """Search for record IDs matching the domain."""
        domain = self._validate_domain(domain)
        self._validate_model(model)
        domain_fields = {
            clause[0] for clause in domain
            if isinstance(clause, (list, tuple)) and clause and isinstance(clause[0], str)
        }
        if domain_fields:
            self._validate_fields(model, list(domain_fields))
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
        
        result = self._execute_with_retry(
            lambda: self.execute(model, "search", domain, **kwargs)
        )
        
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
        domain = self._validate_domain(domain)
        self._validate_model(model)
        if fields:
            self._validate_fields(model, fields)
        domain_fields = {
            clause[0] for clause in domain
            if isinstance(clause, (list, tuple)) and clause and isinstance(clause[0], str)
        }
        if domain_fields:
            self._validate_fields(model, list(domain_fields))
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
        
        result = self._execute_with_retry(
            lambda: self.execute(model, "search_read", domain, **kwargs)
        )
        
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
        self._validate_model(model)
        if fields:
            self._validate_fields(model, fields)
        if isinstance(ids, int):
            ids = [ids]
            single_record = True
        else:
            single_record = False
            
        kwargs: Dict[str, Any] = {}
        if fields is not None:
            kwargs["fields"] = fields
        
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
        self._validate_model(model)
        field_names = set(values.keys() if isinstance(values, dict) else [])
        if isinstance(values, list):
            for value in values:
                field_names.update(value.keys())
        if field_names:
            self._validate_fields(model, sorted(field_names))
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
        self._validate_model(model)
        if values:
            self._validate_fields(model, list(values.keys()))
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
        self._validate_model(model)
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
        return_cache_status: bool = False,
    ) -> Union[Dict[str, Dict[str, Any]], tuple[Dict[str, Dict[str, Any]], str]]:
        """Get field definitions for a model."""
        self._validate_model(model)
        kwargs: Dict[str, Any] = {}
        if fields is not None:
            kwargs["allfields"] = fields
        if attributes is not None:
            kwargs["attributes"] = attributes
        
        cache_status = "miss"
        # Generate cache key
        cache_key = self.cache.generate_key(
            "fields_get", model, str(fields), str(attributes)
        )
        
        # Try cache first (fields don't change often)
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            cache_status = "hit"
            result = cached_result
        else:
            result = self._execute_with_retry(
                lambda: self.execute(model, "fields_get", **kwargs)
            )
            # Cache for longer (1 hour) since fields don't change often
            self.cache.set(cache_key, result, ttl=3600)
        
        if return_cache_status:
            return result, cache_status
        return result

    def get_model_list(self, return_cache_status: bool = False) -> Union[List[Dict[str, Any]], tuple[List[Dict[str, Any]], str]]:
        """Get list of all available models."""
        cache_key = "model_list"
        cache_status = "miss"
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            cache_status = "hit"
            result = cached_result
        else:
            result = self.search_read("ir.model", [], ["model", "name", "transient"])
            # Cache for longer (1 hour) since models don't change often
            self.cache.set(cache_key, result, ttl=3600)
        
        if return_cache_status:
            return result, cache_status
        return result

    def search_count(
        self,
        model: str,
        domain: Optional[List[List[Any]]] = None,
    ) -> int:
        """Count records matching the domain."""
        domain = self._validate_domain(domain)
        self._validate_model(model)
        domain_fields = {
            clause[0] for clause in domain
            if isinstance(clause, (list, tuple)) and clause and isinstance(clause[0], str)
        }
        if domain_fields:
            self._validate_fields(model, list(domain_fields))
        
        # Generate cache key
        cache_key = self.cache.generate_key(
            "search_count", model, str(domain)
        )
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self._execute_with_retry(
            lambda: self.execute(model, "search_count", domain)
        )
        
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

    def list_reports(self, model: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available QWeb PDF reports (ir.actions.report)."""
        domain: List[List[Any]] = [["report_type", "=", "qweb-pdf"]]
        if model:
            domain.append(["model", "=", model])

        reports = self.search_read(
            "ir.actions.report",
            domain,
            ["id", "name", "report_name", "model", "report_type"],
        )

        if search:
            term = search.lower()
            reports = [
                r
                for r in reports
                if term in (r.get("name") or "").lower()
                or term in (r.get("report_name") or "").lower()
            ]
        return reports

    def render_report(
        self,
        report_name: str,
        ids: List[int],
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Render a QWeb PDF report by technical name for given record IDs."""
        if not report_name:
            raise OdooServiceError(
                "invalid_method",
                "Report name is required",
                "Provide a report technical name (e.g., sale.report_saleorder, account.report_invoice)",
                True,
            )
        if not ids:
            raise OdooServiceError(
                "invalid_domain",
                "No record IDs provided for report generation",
                "Pass a non-empty list of record IDs to render",
                True,
            )

        ids = [int(i) for i in ids]
        reports = self.list_reports(search=report_name)
        report_info = next((r for r in reports if r.get("report_name") == report_name), None)
        if not report_info:
            raise OdooServiceError(
                "invalid_method",
                f"Report '{report_name}' not found",
                "Call list_reports to discover available report technical names",
                True,
            )

        def _render_via_report_service():
            return self.report.render_report(
                self.database,
                self.authenticate(),
                self.password,
                report_name,
                ids,
            )

        def _render_via_model(method: str):
            # legacy model methods on report.report (render_report/get_pdf)
            args: List[Any] = [ids, report_name]
            if data is not None:
                args.append(data)
            return self.execute("report.report", method, *args)
        
        def _render_via_http_report() -> bytes:
            """Fallback using Odoo HTTP report route /report/pdf/REPORT/ids."""
            base_url = self.url.rstrip("/")
            login_url = f"{base_url}/web/session/authenticate"
            report_url = f"{base_url}/report/pdf/{report_name}/{','.join(map(str, ids))}"
            try:
                with httpx.Client(verify=self.config.verify_ssl, timeout=self.config.timeout) as client:
                    auth_payload = {
                        "jsonrpc": "2.0",
                        "params": {
                            "db": self.database,
                            "login": self.username,
                            "password": self.password,
                        },
                    }
                    auth_resp = client.post(login_url, json=auth_payload)
                    auth_resp.raise_for_status()
                    auth_json = auth_resp.json()
                    if not auth_json.get("result") or not auth_json["result"].get("session_id"):
                        raise OdooServiceError(
                            "auth_failed",
                            f"Authentication failed for HTTP report: {auth_json}",
                            "Verify Odoo credentials/API key",
                            False,
                        )
                    session_id = auth_json["result"]["session_id"]
                    pdf_resp = client.get(report_url, headers={"Cookie": f"session_id={session_id}"})
                    pdf_resp.raise_for_status()
                    return pdf_resp.content
            except OdooServiceError:
                raise
            except Exception as exc:
                raise OdooServiceError(
                    "transport_error",
                    f"HTTP report fetch failed: {exc}",
                    "Check Odoo URL/network and ensure report endpoints are reachable",
                    True,
                )

        try:
            result = self._execute_with_retry(_render_via_report_service)
        except OdooServiceError as exc:
            # Fallback to model-based rendering if report service is unavailable
            msg = str(exc).lower().replace("\\'", "'")
            if "keyerror: 'report'" in msg or ("keyerror" in msg and "report" in msg) or "does not exist" in msg or "unknown" in msg:
                try:
                    result = self._execute_with_retry(lambda: _render_via_model("render_report"))
                except OdooServiceError:
                    try:
                        result = self._execute_with_retry(lambda: _render_via_model("get_pdf"))
                    except OdooServiceError:
                        # Last resort: HTTP download of report
                        pdf_bytes = _render_via_http_report()
                        encoded = base64.b64encode(pdf_bytes).decode("ascii")
                        return {
                            "report_name": report_name,
                            "report_label": report_info.get("name"),
                            "model": report_info.get("model"),
                            "ids": ids,
                            "size_bytes": len(pdf_bytes),
                            "pdf_base64": encoded,
                        }
            else:
                raise exc
        pdf_bytes: bytes
        if isinstance(result, dict) and "result" in result:
            raw = result["result"]
            if isinstance(raw, str):
                pdf_bytes = base64.b64decode(raw)
            elif isinstance(raw, (bytes, bytearray)):
                pdf_bytes = bytes(raw)
            else:
                pdf_bytes = bytes(raw)
        elif isinstance(result, (list, tuple)) and result:
            first = result[0]
            if isinstance(first, str):
                pdf_bytes = base64.b64decode(first)
            elif isinstance(first, (bytes, bytearray)):
                pdf_bytes = bytes(first)
            else:
                pdf_bytes = bytes(first)
        elif isinstance(result, (bytes, bytearray)):
            pdf_bytes = bytes(result)
        else:
            raise OdooServiceError(
                "unknown",
                f"Unexpected report response type: {type(result)}",
                "Verify the report name and try again",
                False,
            )

        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        return {
            "report_name": report_name,
            "report_label": report_info.get("name"),
            "model": report_info.get("model"),
            "ids": ids,
            "size_bytes": len(pdf_bytes),
            "pdf_base64": encoded,
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
