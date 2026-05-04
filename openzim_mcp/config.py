"""Configuration management for OpenZIM MCP server."""

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .defaults import CACHE, CONTENT, VALID_TOOL_MODES
from .exceptions import OpenZimMcpConfigurationError
from .rate_limiter import RateLimitConfig

__all__ = [
    "CacheConfig",
    "ContentConfig",
    "LoggingConfig",
    "OpenZimMcpConfig",
    "RateLimitConfig",
]


class CacheConfig(BaseModel):
    """Cache configuration settings."""

    enabled: bool = True
    max_size: int = Field(default=CACHE.MAX_SIZE, ge=1, le=10000)
    ttl_seconds: int = Field(default=CACHE.TTL_SECONDS, ge=60, le=86400)
    persistence_enabled: bool = Field(default=CACHE.PERSISTENCE_ENABLED)
    persistence_path: str = Field(default_factory=lambda: CACHE.PERSISTENCE_PATH)

    @field_validator("persistence_path")
    @classmethod
    def normalize_persistence_path(cls, v: str) -> str:
        """Normalize persistence_path to an absolute, tilde-expanded path.

        Without this, a CWD-relative default (or user-supplied relative
        path) lands in unpredictable locations under containers/systemd
        where the working directory is not the user's home.
        """
        return str(Path(v).expanduser().resolve())


class ContentConfig(BaseModel):
    """Content processing configuration."""

    max_content_length: int = Field(default=CONTENT.MAX_CONTENT_LENGTH, ge=100)
    snippet_length: int = Field(default=CONTENT.SNIPPET_LENGTH, ge=100)
    default_search_limit: int = Field(default=CONTENT.SEARCH_LIMIT, ge=1, le=100)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(default="INFO")
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @field_validator("level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v.upper()


class OpenZimMcpConfig(BaseSettings):
    """Main configuration for OpenZIM MCP server."""

    # Directory settings
    allowed_directories: List[str] = Field(default_factory=list)

    # Component configurations
    cache: CacheConfig = Field(default_factory=CacheConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

    # Server settings
    server_name: str = "openzim-mcp"
    tool_mode: Literal["advanced", "simple"] = Field(
        default="simple",
        description=(
            "Tool mode: 'advanced' for all 21 tools, "
            "'simple' for 1 intelligent tool plus underlying tools"
        ),
    )
    transport: Literal["stdio", "http", "sse"] = Field(
        default="stdio",
        description=(
            "Transport protocol: 'stdio' (default), 'http' (streamable HTTP), "
            "or 'sse' (legacy SSE — no auth middleware, intended for local use)"
        ),
    )
    host: str = Field(
        default="127.0.0.1",
        description="HTTP bind host (only used when transport='http' or 'sse')",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="HTTP bind port (only used when transport='http' or 'sse')",
    )
    auth_token: Optional[SecretStr] = Field(
        default=None,
        description=(
            "Bearer token for HTTP transport. Loaded from env var "
            "OPENZIM_MCP_AUTH_TOKEN. Never set this in a config file."
        ),
    )
    cors_origins: List[str] = Field(
        default_factory=list,
        description=(
            "CORS allow-list. Wildcard '*' is rejected. Default is empty "
            "(no CORS headers emitted)."
        ),
    )
    allowed_hosts: List[str] = Field(
        default_factory=list,
        description=(
            "Public-facing hostnames the HTTP transport accepts in the "
            "Host header (e.g. ['mcp.example.com']). Loopback values "
            "('127.0.0.1', 'localhost', '[::1]') are always allowed; this "
            "setting extends them when openzim-mcp sits behind a reverse "
            "proxy or Tailscale serve, which preserve the original Host. "
            "Entries may be exact ('mcp.example.com') or include the "
            "':*' wildcard-port suffix ('mcp.example.com:*'). Wildcard "
            "'*' alone is rejected. Honored only when transport='http'."
        ),
    )
    watch_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Polling interval for resource subscriptions (seconds).",
    )
    subscriptions_enabled: bool = Field(
        default=True,
        description=(
            "Master switch for resource subscriptions. When False, the "
            "polling task is not started and subscribe calls succeed but "
            "never fire updates."
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="OPENZIM_MCP_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @field_validator("allowed_directories")
    @classmethod
    def validate_directories(cls, v: List[str]) -> List[str]:
        """Validate that all directories exist and are accessible."""
        if not v:
            raise OpenZimMcpConfigurationError(
                "At least one allowed directory must be specified"
            )

        validated_dirs = []
        for dir_path in v:
            path = Path(dir_path).expanduser().resolve()
            if not path.exists():
                raise OpenZimMcpConfigurationError(f"Directory does not exist: {path}")
            if not path.is_dir():
                raise OpenZimMcpConfigurationError(f"Path is not a directory: {path}")
            validated_dirs.append(str(path))

        return validated_dirs

    @field_validator("tool_mode")
    @classmethod
    def validate_tool_mode(cls, v: str) -> str:
        """Validate tool mode."""
        if v not in VALID_TOOL_MODES:
            raise OpenZimMcpConfigurationError(
                f"Invalid tool mode: {v}. Must be one of {VALID_TOOL_MODES}"
            )
        return v

    @field_validator("cors_origins")
    @classmethod
    def reject_cors_wildcard(cls, v: List[str]) -> List[str]:
        """Reject wildcard '*' in CORS origins (footgun prevention).

        Strips each origin before comparing so whitespace-padded variants
        like ``" * "`` cannot bypass the check.
        """
        if any(origin.strip() == "*" for origin in v):
            raise OpenZimMcpConfigurationError(
                "CORS wildcard '*' is not allowed. List origins explicitly "
                "(e.g. ['http://localhost:5173'])."
            )
        return v

    @field_validator("allowed_hosts")
    @classmethod
    def reject_allowed_hosts_wildcard(cls, v: List[str]) -> List[str]:
        """Reject wildcard '*' in allowed_hosts (footgun prevention).

        DNS rebinding protection is the whole point of the allow-list;
        accepting '*' would defeat it. Whitespace-padded variants are
        normalized before comparison.
        """
        if any(host.strip() == "*" for host in v):
            raise OpenZimMcpConfigurationError(
                "allowed_hosts wildcard '*' is not allowed. List hostnames "
                "explicitly (e.g. ['mcp.example.com'])."
            )
        return v

    def setup_logging(self) -> None:
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.logging.level),
            format=self.logging.format,
            force=True,
        )

    def get_config_hash(self) -> str:
        """
        Generate a hash fingerprint of the current configuration.

        This hash is used to detect configuration conflicts between
        multiple server instances. Only configuration elements that
        affect server behavior are included in the hash.

        Returns:
            SHA-256 hash of the configuration as a hex string
        """
        # Create a normalized configuration dict for hashing
        config_for_hash = {
            "allowed_directories": sorted(
                self.allowed_directories
            ),  # Sort for consistency
            "cache_enabled": self.cache.enabled,
            "cache_max_size": self.cache.max_size,
            "cache_ttl_seconds": self.cache.ttl_seconds,
            "content_max_length": self.content.max_content_length,
            "content_snippet_length": self.content.snippet_length,
            "search_default_limit": self.content.default_search_limit,
            "server_name": self.server_name,
            "tool_mode": self.tool_mode,
            "transport": self.transport,
            "host": self.host,
            "port": self.port,
            "cors_origins": sorted(self.cors_origins),
            "allowed_hosts": sorted(self.allowed_hosts),
            "watch_interval_seconds": self.watch_interval_seconds,
            "subscriptions_enabled": self.subscriptions_enabled,
            "rate_limit_enabled": self.rate_limit.enabled,
            "rate_limit_rps": self.rate_limit.requests_per_second,
            "rate_limit_burst": self.rate_limit.burst_size,
        }

        # Convert to JSON string with sorted keys for consistent hashing
        config_json = json.dumps(config_for_hash, sort_keys=True, separators=(",", ":"))

        # Generate SHA-256 hash
        return hashlib.sha256(config_json.encode("utf-8")).hexdigest()
