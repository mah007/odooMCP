"""Logging configuration using Loguru."""

import sys
from pathlib import Path
from typing import Optional
from loguru import logger

from .config import get_config


def setup_logging(log_file: Optional[str] = None) -> None:
    """Setup Loguru logging configuration."""
    # Remove default handler
    logger.remove()
    
    # Console handler with colors
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
        filter=lambda record: record["name"].startswith("mcp_server_odoo")
    )
    
    # File handler with rotation (only if we can write to the directory)
    try:
        # Try to use project logs directory first
        log_path = Path("logs/odoo_mcp_server.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        try:
            # Fallback to user's home directory
            log_path = Path.home() / ".odoo_mcp_server" / "logs" / "odoo_mcp_server.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            # If all else fails, skip file logging
            logger.warning("Could not create log directory, file logging disabled")
            return
    
    logger.add(
        log_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        filter=lambda record: record["name"].startswith("mcp_server_odoo")
    )

    config = get_config()
    if config.server.log_level == "DEBUG":
        # Enable debug logging for our modules only
        logger.add(
            sys.stdout,
            level="WARNING",
            filter=lambda record: not record["name"].startswith("mcp_server_odoo"),
            format="<dim>{time:HH:mm:ss}</dim> | <level>{level: <8}</level> | {name} - {message}",
        )


def get_logger(name: str):
    """Get a logger instance for the given name."""
    return logger.bind(name=name)


# Initialize logging on import
setup_logging()
