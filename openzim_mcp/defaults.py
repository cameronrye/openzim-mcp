"""
Centralized default values for OpenZIM MCP server configuration.

This module consolidates all default configuration values in one place,
making it easier to understand and modify the server's default behavior.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


def _default_persistence_path() -> str:
    """Return the default cache persistence path as a resolved absolute path.

    Uses ``~/.cache/openzim-mcp`` rather than a CWD-relative path so the
    cache lands in a predictable location regardless of how the server is
    invoked (containers, systemd units, etc. often run from ``/`` and a
    relative default would silently land in the working directory or in a
    world-writable surface).
    """
    return str((Path.home() / ".cache" / "openzim-mcp").resolve())


@dataclass(frozen=True)
class CacheDefaults:
    """Default values for cache configuration."""

    ENABLED: bool = True
    MAX_SIZE: int = 100
    TTL_SECONDS: int = 3600  # 1 hour
    PERSISTENCE_ENABLED: bool = False
    PERSISTENCE_PATH: str = field(default_factory=_default_persistence_path)


@dataclass(frozen=True)
class ContentDefaults:
    """Default values for content processing."""

    SNIPPET_LENGTH: int = 1000
    MAX_CONTENT_LENGTH: int = 100000
    SEARCH_LIMIT: int = 10
    MAX_BINARY_SIZE: int = 10_000_000  # 10MB
    MAIN_PAGE_TRUNCATION: int = 5000  # Characters for main page display
    # Maximum redirect chain length before bailing out. Real ZIM redirects
    # rarely chain more than once or twice; ten is well above any legitimate
    # depth and guards against pathological data or cycles libzim itself
    # does not detect.
    MAX_REDIRECT_DEPTH: int = 10


@dataclass(frozen=True)
class RateLimitDefaults:
    """Default values for rate limiting."""

    ENABLED: bool = True
    REQUESTS_PER_SECOND: float = 10.0
    BURST_SIZE: int = 20


@dataclass(frozen=True)
class InputLimitDefaults:
    """Default values for input validation limits."""

    FILE_PATH: int = 1000
    QUERY: int = 500
    ENTRY_PATH: int = 500
    NAMESPACE: int = 100
    CONTENT_TYPE: int = 100
    PARTIAL_QUERY: int = 200


@dataclass(frozen=True)
class CachePerformanceThresholds:
    """Threshold values for cache performance analysis."""

    LOW_HIT_RATE: float = 0.3  # Below this is considered poor performance
    HIGH_HIT_RATE: float = 0.8  # Above this is considered good performance


@dataclass(frozen=True)
class NamespaceSamplingDefaults:
    """Default values for namespace discovery sampling."""

    MAX_SAMPLE_SIZE: int = 1000  # Maximum entries to sample for namespace discovery
    MAX_NAMESPACE_ENTRIES: int = 200  # Maximum entries to collect per namespace
    MAX_SAMPLE_ATTEMPTS_MULTIPLIER: int = 3  # sample_size * multiplier = max attempts


@dataclass(frozen=True)
class TimeoutDefaults:
    """Default values for timeouts."""

    REGEX_SECONDS: float = 1.0
    ARCHIVE_OPEN_SECONDS: float = 30.0
    # Per-subscriber timeout for ``send_resource_updated`` during broadcast.
    # A subscriber that doesn't respond within this window is treated as dead
    # and evicted from the registry. The fan-out is concurrent
    # (``asyncio.gather``), so one hung subscriber never delays the others —
    # this timeout only bounds how long an individual hung send blocks its
    # own task before being cancelled.
    SUBSCRIPTION_SEND_SECONDS: float = 5.0


@dataclass(frozen=True)
class ServerDefaults:
    """Default values for server configuration."""

    NAME: str = "openzim-mcp"
    TOOL_MODE: str = "simple"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass(frozen=True)
class BatchDefaults:
    """Default values for batch operations."""

    MAX_SIZE: int = 50  # max entries per get_zim_entries call


# Instantiate defaults for easy access
CACHE = CacheDefaults()
CONTENT = ContentDefaults()
RATE_LIMIT = RateLimitDefaults()
INPUT_LIMITS = InputLimitDefaults()
TIMEOUTS = TimeoutDefaults()
SERVER = ServerDefaults()
CACHE_PERFORMANCE = CachePerformanceThresholds()
NAMESPACE_SAMPLING = NamespaceSamplingDefaults()
BATCH = BatchDefaults()

# Tool mode constants
TOOL_MODE_ADVANCED = "advanced"
TOOL_MODE_SIMPLE = "simple"
VALID_TOOL_MODES = {TOOL_MODE_ADVANCED, TOOL_MODE_SIMPLE}

# File validation constants
ZIM_FILE_EXTENSION = ".zim"

# Valid transport types for MCP server
VALID_TRANSPORT_TYPES = {"stdio", "sse", "streamable-http"}

# HTML processing constants - selectors to remove during content processing
UNWANTED_HTML_SELECTORS: List[str] = [
    "script",
    "style",
    "meta",
    "link",
    "head",
    "footer",
    ".mw-parser-output .reflist",
    ".mw-editsection",
]

# Rate limiter operation costs
RATE_LIMIT_COSTS: Dict[str, int] = {
    "search": 2,
    "search_with_filters": 2,
    "find_entry_by_title": 2,
    "get_entry": 1,
    "get_zim_entries": 1,
    "get_binary_entry": 3,
    "browse_namespace": 1,
    "get_metadata": 1,
    "get_structure": 1,
    "get_related_articles": 2,
    "suggestions": 1,
    "default": 1,
}
