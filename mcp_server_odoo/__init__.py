"""MCP server for Odoo integration with HTTP streaming transport."""

__version__ = "1.0.0"

from .config import get_config
from .logger import get_logger
from .services import OdooService, CacheService

__all__ = [
    "get_config",
    "get_logger", 
    "OdooService",
    "CacheService",
]