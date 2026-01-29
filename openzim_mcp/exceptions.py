"""
Custom exceptions for OpenZIM MCP server.

Each exception has an error_code for programmatic handling and categorization.
Error codes follow the pattern: OPENZIM_<CATEGORY>_<SPECIFIC>
"""

from typing import Optional


class OpenZimMcpError(Exception):
    """Base exception for all OpenZIM MCP-related errors.

    Attributes:
        error_code: Unique error code for programmatic handling
        message: Human-readable error message
        details: Optional additional details about the error
    """

    error_code: str = "OPENZIM_ERROR"

    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """Convert exception to a dictionary for JSON serialization."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class OpenZimMcpSecurityError(OpenZimMcpError):
    """Raised when security validation fails."""

    error_code: str = "OPENZIM_SECURITY_VIOLATION"


class OpenZimMcpValidationError(OpenZimMcpError):
    """Raised when input validation fails."""

    error_code: str = "OPENZIM_VALIDATION_ERROR"


class OpenZimMcpFileNotFoundError(OpenZimMcpError):
    """Raised when a ZIM file is not found."""

    error_code: str = "OPENZIM_FILE_NOT_FOUND"


class OpenZimMcpArchiveError(OpenZimMcpError):
    """Raised when ZIM archive operations fail."""

    error_code: str = "OPENZIM_ARCHIVE_ERROR"


class OpenZimMcpConfigurationError(OpenZimMcpError):
    """Raised when configuration is invalid."""

    error_code: str = "OPENZIM_CONFIG_ERROR"


class OpenZimMcpTimeoutError(OpenZimMcpError):
    """Base class for timeout-related errors."""

    error_code: str = "OPENZIM_TIMEOUT"


class ArchiveOpenTimeoutError(OpenZimMcpTimeoutError):
    """Raised when opening a ZIM archive times out."""

    error_code: str = "OPENZIM_ARCHIVE_OPEN_TIMEOUT"


class RegexTimeoutError(OpenZimMcpTimeoutError):
    """Raised when a regex operation times out."""

    error_code: str = "OPENZIM_REGEX_TIMEOUT"


class OpenZimMcpRateLimitError(OpenZimMcpError):
    """Raised when rate limit is exceeded."""

    error_code: str = "OPENZIM_RATE_LIMIT_EXCEEDED"
