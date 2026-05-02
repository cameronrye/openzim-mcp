"""Custom exceptions for OpenZIM MCP server.

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

    def __init__(self, message: str, details: Optional[str] = None):  # noqa: B042
        """Initialize the exception.

        Args:
            message: Human-readable error message
            details: Optional additional details about the error
        """
        self.message = message
        self.details = details
        # Pass only ``message`` to ``Exception.__init__``: ``Exception.args``
        # ends up as ``(message,)`` rather than ``(message, details)``, so
        # ``repr(error)`` no longer leaks operational metadata (rate-limit
        # cost breakdowns, request IDs, etc.) into tracebacks. ``details``
        # remains accessible programmatically via ``self.details``. The B042
        # exception (pickle/copy edge cases) is acceptable here because we
        # do not pickle these errors across process boundaries.
        super().__init__(message)

    def __str__(self) -> str:
        """Return the error message."""
        return self.message


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
