"""
Custom exceptions for OpenZIM MCP server.
"""

from typing import Optional


class OpenZimMcpError(Exception):
    """Base exception for all OpenZIM MCP-related errors."""

    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class OpenZimMcpSecurityError(OpenZimMcpError):
    """Raised when security validation fails."""

    pass


class OpenZimMcpValidationError(OpenZimMcpError):
    """Raised when input validation fails."""

    pass


class OpenZimMcpFileNotFoundError(OpenZimMcpError):
    """Raised when a ZIM file is not found."""

    pass


class OpenZimMcpArchiveError(OpenZimMcpError):
    """Raised when ZIM archive operations fail."""

    pass


class OpenZimMcpConfigurationError(OpenZimMcpError):
    """Raised when configuration is invalid."""

    pass
