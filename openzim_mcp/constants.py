"""
Constants used throughout the OpenZIM MCP server.
"""

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
