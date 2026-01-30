"""Configuration management for OpenZIM MCP server."""

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import (
    DEFAULT_CACHE_PERSISTENCE_ENABLED,
    DEFAULT_CACHE_PERSISTENCE_PATH,
    DEFAULT_CACHE_SIZE,
    DEFAULT_CACHE_TTL,
    DEFAULT_MAX_CONTENT_LENGTH,
    DEFAULT_RATE_LIMIT_BURST,
    DEFAULT_RATE_LIMIT_ENABLED,
    DEFAULT_RATE_LIMIT_RPS,
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SNIPPET_LENGTH,
    VALID_TOOL_MODES,
)
from .exceptions import OpenZimMcpConfigurationError


class CacheConfig(BaseModel):
    """Cache configuration settings."""

    enabled: bool = True
    max_size: int = Field(default=DEFAULT_CACHE_SIZE, ge=1, le=10000)
    ttl_seconds: int = Field(default=DEFAULT_CACHE_TTL, ge=60, le=86400)
    persistence_enabled: bool = Field(default=DEFAULT_CACHE_PERSISTENCE_ENABLED)
    persistence_path: str = Field(default=DEFAULT_CACHE_PERSISTENCE_PATH)


class RateLimitConfig(BaseModel):
    """Rate limiting configuration settings."""

    enabled: bool = Field(default=DEFAULT_RATE_LIMIT_ENABLED)
    requests_per_second: float = Field(default=DEFAULT_RATE_LIMIT_RPS, gt=0)
    burst_size: int = Field(default=DEFAULT_RATE_LIMIT_BURST, ge=1, le=1000)


class ContentConfig(BaseModel):
    """Content processing configuration."""

    max_content_length: int = Field(default=DEFAULT_MAX_CONTENT_LENGTH, ge=1000)
    snippet_length: int = Field(default=DEFAULT_SNIPPET_LENGTH, ge=100)
    default_search_limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=100)


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
            "Tool mode: 'advanced' for all 18 tools, "
            "'simple' for 1 intelligent tool plus underlying tools"
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
            "rate_limit_enabled": self.rate_limit.enabled,
            "rate_limit_rps": self.rate_limit.requests_per_second,
            "rate_limit_burst": self.rate_limit.burst_size,
        }

        # Convert to JSON string with sorted keys for consistent hashing
        config_json = json.dumps(config_for_hash, sort_keys=True, separators=(",", ":"))

        # Generate SHA-256 hash
        return hashlib.sha256(config_json.encode("utf-8")).hexdigest()
