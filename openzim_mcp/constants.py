"""
Constants used throughout the OpenZIM MCP server.

NOTE: This module re-exports values from defaults.py for backward compatibility.
New code should import from defaults.py directly for access to the structured
defaults classes.
"""

# Import from centralized defaults for backward compatibility
# These are re-exported for external consumers
from .defaults import (  # noqa: F401
    BATCH,
    CACHE,
    CACHE_PERFORMANCE,
    CONTENT,
    FURNITURE_HEADING_DENYLIST,
    FURNITURE_HEADING_PREFIXES,
    INPUT_LIMITS,
    NAMESPACE_SAMPLING,
    RATE_LIMIT,
    SEARCH,
    SERVER,
    TIMEOUTS,
    TOOL_MODE_ADVANCED,
    TOOL_MODE_SIMPLE,
    UNWANTED_HTML_SELECTORS,
    VALID_TOOL_MODES,
    VALID_TRANSPORT_TYPES,
    ZIM_FILE_EXTENSION,
)

# Re-export legacy constant names for backward compatibility
# Content processing constants
DEFAULT_SNIPPET_LENGTH = CONTENT.SNIPPET_LENGTH
DEFAULT_MAX_CONTENT_LENGTH = CONTENT.MAX_CONTENT_LENGTH
DEFAULT_SEARCH_LIMIT = CONTENT.SEARCH_LIMIT
# Upper bound on a caller-supplied search/query ``limit`` (see
# ``SearchDefaults.MAX_RESULT_LIMIT``).
MAX_SEARCH_RESULT_LIMIT = SEARCH.MAX_RESULT_LIMIT

# Cache configuration
DEFAULT_CACHE_SIZE = CACHE.MAX_SIZE
DEFAULT_CACHE_TTL = CACHE.TTL_SECONDS

# Binary content retrieval constants
DEFAULT_MAX_BINARY_SIZE = CONTENT.MAX_BINARY_SIZE

# Batch operation limits
MAX_BATCH_SIZE = BATCH.MAX_SIZE

# Input validation limits
INPUT_LIMIT_FILE_PATH = INPUT_LIMITS.FILE_PATH
INPUT_LIMIT_QUERY = INPUT_LIMITS.QUERY
INPUT_LIMIT_ENTRY_PATH = INPUT_LIMITS.ENTRY_PATH
INPUT_LIMIT_NAMESPACE = INPUT_LIMITS.NAMESPACE
INPUT_LIMIT_CONTENT_TYPE = INPUT_LIMITS.CONTENT_TYPE
INPUT_LIMIT_PARTIAL_QUERY = INPUT_LIMITS.PARTIAL_QUERY

# Regex timeout for intent parsing (seconds)
REGEX_TIMEOUT_SECONDS = TIMEOUTS.REGEX_SECONDS

# Main page display
DEFAULT_MAIN_PAGE_TRUNCATION = CONTENT.MAIN_PAGE_TRUNCATION

# Cache performance thresholds
CACHE_LOW_HIT_RATE_THRESHOLD = CACHE_PERFORMANCE.LOW_HIT_RATE
CACHE_HIGH_HIT_RATE_THRESHOLD = CACHE_PERFORMANCE.HIGH_HIT_RATE

# Namespace sampling
NAMESPACE_MAX_SAMPLE_SIZE = NAMESPACE_SAMPLING.MAX_SAMPLE_SIZE
NAMESPACE_MAX_ENTRIES = NAMESPACE_SAMPLING.MAX_NAMESPACE_ENTRIES
NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER = NAMESPACE_SAMPLING.MAX_SAMPLE_ATTEMPTS_MULTIPLIER

# Declare the full public surface. This module is a backward-compat facade:
# the names below are re-exported for external consumers (and several are
# imported by sibling modules), so they are intentionally "unused" within
# this file. Listing them in ``__all__`` marks them as the public API,
# which suppresses the CodeQL ``py/unused-import`` note (it honours
# ``__all__`` membership) the same way the per-line ``# noqa: F401`` silences
# flake8 — without deleting re-exports the package depends on.
__all__ = [
    # Structured defaults re-exported from ``defaults`` (new code should
    # import these from ``openzim_mcp.defaults`` directly).
    "BATCH",
    "CACHE",
    "CACHE_PERFORMANCE",
    "CONTENT",
    "FURNITURE_HEADING_DENYLIST",
    "FURNITURE_HEADING_PREFIXES",
    "INPUT_LIMITS",
    "NAMESPACE_SAMPLING",
    "RATE_LIMIT",
    "SERVER",
    "TIMEOUTS",
    "TOOL_MODE_ADVANCED",
    "TOOL_MODE_SIMPLE",
    "UNWANTED_HTML_SELECTORS",
    "VALID_TOOL_MODES",
    "VALID_TRANSPORT_TYPES",
    "ZIM_FILE_EXTENSION",
    # Legacy flat constant names (derived above) kept for backward compat.
    "DEFAULT_SNIPPET_LENGTH",
    "DEFAULT_MAX_CONTENT_LENGTH",
    "DEFAULT_SEARCH_LIMIT",
    "MAX_SEARCH_RESULT_LIMIT",
    "DEFAULT_CACHE_SIZE",
    "DEFAULT_CACHE_TTL",
    "DEFAULT_MAX_BINARY_SIZE",
    "MAX_BATCH_SIZE",
    "INPUT_LIMIT_FILE_PATH",
    "INPUT_LIMIT_QUERY",
    "INPUT_LIMIT_ENTRY_PATH",
    "INPUT_LIMIT_NAMESPACE",
    "INPUT_LIMIT_CONTENT_TYPE",
    "INPUT_LIMIT_PARTIAL_QUERY",
    "REGEX_TIMEOUT_SECONDS",
    "DEFAULT_MAIN_PAGE_TRUNCATION",
    "CACHE_LOW_HIT_RATE_THRESHOLD",
    "CACHE_HIGH_HIT_RATE_THRESHOLD",
    "NAMESPACE_MAX_SAMPLE_SIZE",
    "NAMESPACE_MAX_ENTRIES",
    "NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER",
]
