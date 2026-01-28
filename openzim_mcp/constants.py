"""
Constants used throughout the OpenZIM MCP server.
"""

# Tool mode constants
TOOL_MODE_ADVANCED = "advanced"
TOOL_MODE_SIMPLE = "simple"
VALID_TOOL_MODES = {TOOL_MODE_ADVANCED, TOOL_MODE_SIMPLE}

# Content processing constants
DEFAULT_SNIPPET_LENGTH = 1000
DEFAULT_MAX_CONTENT_LENGTH = 100000
DEFAULT_SEARCH_LIMIT = 10
DEFAULT_SEARCH_OFFSET = 0

# File validation constants
ZIM_FILE_EXTENSION = ".zim"
SUPPORTED_MIME_TYPES = {
    "text/html",
    "text/plain",
    "text/markdown",
    "text/css",
    "text/javascript",
}

# HTML processing constants
UNWANTED_HTML_SELECTORS = [
    "script",
    "style",
    "meta",
    "link",
    "head",
    "footer",
    ".mw-parser-output .reflist",
    ".mw-editsection",
]

# Logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Cache configuration
DEFAULT_CACHE_SIZE = 100
DEFAULT_CACHE_TTL = 3600  # 1 hour in seconds

# Binary content retrieval constants
DEFAULT_MAX_BINARY_SIZE = 10_000_000  # 10MB default limit for binary content

# Input validation limits (for sanitize_input)
# These limits prevent resource exhaustion and ensure reasonable input sizes
INPUT_LIMIT_FILE_PATH = 1000  # Maximum length for file paths
INPUT_LIMIT_QUERY = 500  # Maximum length for search queries
INPUT_LIMIT_ENTRY_PATH = 500  # Maximum length for entry paths
INPUT_LIMIT_NAMESPACE = 100  # Maximum length for namespace identifiers
INPUT_LIMIT_CONTENT_TYPE = 100  # Maximum length for content type strings
INPUT_LIMIT_PARTIAL_QUERY = 200  # Maximum length for autocomplete queries

# Regex timeout for intent parsing (seconds)
REGEX_TIMEOUT_SECONDS = 1.0

# Valid transport types for MCP server
VALID_TRANSPORT_TYPES = {"stdio", "sse", "streamable-http"}
