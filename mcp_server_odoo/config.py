"""Configuration management for Odoo MCP Server."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from pydantic import AliasChoices, BaseModel, Field, field_validator

# Load environment variables
load_dotenv()


class OdooConfig(BaseModel):
    """Configuration for Odoo connection."""

    url: str = Field(..., description="Odoo instance URL")
    database: str = Field(..., description="Odoo database name", validation_alias=AliasChoices("database", "db"))
    username: str = Field(..., description="Odoo username (e.g. email)")
    password: Optional[str] = Field(None, description="Odoo password")
    api_key: Optional[str] = Field(None, description="Odoo API key")
    timeout: int = Field(120, description="Request timeout in seconds")
    version: str = Field("18.0", description="Odoo version (e.g. '18.0' or '19.0')")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize URL."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout value."""
        if v <= 0:
            raise ValueError("Timeout must be positive")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Ensure the version is one of the supported options."""
        normalized = v.strip()
        if normalized not in {"18.0", "19.0"}:
            raise ValueError("Version must be one of: 18.0, 19.0")
        return normalized

    def model_post_init(self, __context: Any) -> None:
        """Validate that either password or api_key is provided."""
        if not self.password and not self.api_key:
            raise ValueError("Either password or api_key must be provided")

    def get_endpoints(self) -> Dict[str, str]:
        """Return XML-RPC endpoints derived from the configured version."""
        common_path = "/xmlrpc/2/common"
        object_path = "/xmlrpc/2/object"
        # The XML-RPC endpoints stay the same for 18.0 and 19.0; keeping the branch
        # allows a future switch to JSON-RPC without touching callers.
        if self.version == "19.0":
            endpoint_mode = "xmlrpc2"
        else:
            endpoint_mode = "xmlrpc2"

        base_url = f"{self.url}/"
        return {
            "common": f"{base_url.rstrip('/')}{common_path}",
            "object": f"{base_url.rstrip('/')}{object_path}",
            "endpoint_mode": endpoint_mode,
        }


class ServerConfig(BaseModel):
    """Configuration for MCP server."""
    
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Log level")
    api_key: Optional[str] = Field(default=None, description="API key for server authentication")
    
    @field_validator('port')
    @classmethod
    def validate_port(cls, v):
        """Validate port number."""
        if not 1 <= v <= 65535:
            raise ValueError('Port must be between 1 and 65535')
        return v
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'Log level must be one of: {valid_levels}')
        return v.upper()


class CacheConfig(BaseModel):
    """Configuration for caching."""
    
    enabled: bool = Field(default=True, description="Enable caching")
    ttl: int = Field(default=300, description="Cache TTL in seconds")
    max_size: int = Field(default=1000, description="Maximum cache size")
    
    @field_validator('ttl')
    @classmethod
    def validate_ttl(cls, v):
        """Validate TTL value."""
        if v < 0:
            raise ValueError('TTL must be non-negative')
        return v
    
    @field_validator('max_size')
    @classmethod
    def validate_max_size(cls, v):
        """Validate max cache size."""
        if v < 0:
            raise ValueError('Max size must be non-negative')
        return v


class Config(BaseModel):
    """Main configuration class."""
    
    odoo: OdooConfig
    server: ServerConfig = Field(default_factory=ServerConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create configuration from environment variables."""
        # Odoo configuration (required)
        odoo_config = OdooConfig(
            url=os.environ["ODOO_URL"],
            database=os.environ["ODOO_DB"],
            username=os.environ["ODOO_USERNAME"],
            password=os.environ.get("ODOO_PASSWORD"),
            api_key=os.environ.get("ODOO_API_KEY"),
            timeout=int(os.environ.get("ODOO_TIMEOUT", "120")),
            version=os.environ.get("ODOO_VERSION", "18.0"),
        )
        
        # Server configuration (optional with defaults)
        server_config = ServerConfig(
            host=os.environ.get("MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT", "8000")),
            debug=os.environ.get("MCP_DEBUG", "false").lower() == "true",
            log_level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
            api_key=os.environ.get("MCP_API_KEY"),
        )
        
        # Cache configuration (optional with defaults)
        cache_config = CacheConfig(
            enabled=os.environ.get("CACHE_ENABLED", "true").lower() == "true",
            ttl=int(os.environ.get("CACHE_TTL", "300")),
            max_size=int(os.environ.get("CACHE_MAX_SIZE", "1000")),
        )
        
        return cls(
            odoo=odoo_config,
            server=server_config,
            cache=cache_config
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Create configuration from a YAML file."""
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.model_validate(data)


# Global configuration instance
config: Optional[Config] = None


def get_config() -> Config:
    """Get configuration instance."""
    global config
    if config is None:
        load_dotenv()
        config_path = Path(os.environ.get("CONFIG_FILE", "config.yml"))

        if config_path.exists():
            try:
                config = Config.from_yaml(config_path)
            except Exception:
                # Fall back to environment variables if YAML is invalid
                try:
                    config = Config.from_env()
                except KeyError as exc:
                    missing = exc.args[0]
                    raise ValueError(f"Missing required configuration value: {missing}") from exc
        else:
            try:
                config = Config.from_env()
            except KeyError as exc:
                missing = exc.args[0]
                raise ValueError(
                    f"Missing required configuration value: {missing}. "
                    "Provide CONFIG_FILE or set the ODOO_URL/ODOO_DB/ODOO_USERNAME variables."
                ) from exc
    return config
